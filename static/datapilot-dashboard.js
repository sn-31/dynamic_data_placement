const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function formatBytes(bytes) {
    const value = Number(bytes || 0);
    if (!value) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
    return `${(value / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function setConnection(online) {
    const badge = $('#connectionStatus');
    badge.classList.toggle('offline', !online);
    $('#connectionText').textContent = online ? 'Connected' : 'Reconnecting…';
}

async function prepareUserLink() {
    let link = new URL('/upload', window.location.origin).toString();
    try {
        const response = await fetch('/api/network-info');
        if (response.ok) {
            const network = await response.json();
            if (['localhost', '127.0.0.1', '::1'].includes(window.location.hostname) && network.host_ip && network.host_ip !== '127.0.0.1') {
                link = network.user_url || `http://${network.host_ip}:${network.port || 5000}/upload`;
            }
        }
    } catch (error) {
        // Keep the current origin if local address discovery is unavailable.
    }
    $('#shareUserUrl').value = link;
    $('#openUserPortal').href = link;
}

$('#copyUserLink').addEventListener('click', async () => {
    const input = $('#shareUserUrl');
    try {
        if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(input.value);
        else {
            input.select();
            document.execCommand('copy');
            input.setSelectionRange(0, 0);
        }
        $('#copyUserLink').textContent = 'Copied';
        window.setTimeout(() => { $('#copyUserLink').textContent = 'Copy'; }, 1600);
    } catch (error) {
        input.select();
    }
});

const stageOrder = ['received', 'metadata', 'model', 'placement', 'storing', 'stored'];
const stageDetails = {
    received: { label: 'Upload received', note: 'File arrived from the user', progress: 8 },
    metadata: { label: 'Reading metadata', note: 'Preparing file facts for the model', progress: 28 },
    model: { label: 'ML prediction', note: 'Random Forest is classifying the file', progress: 52 },
    placement: { label: 'Choosing node', note: 'Controller is applying the prediction', progress: 76 },
    storing: { label: 'Moving file', note: 'Writing to the selected node', progress: 91 },
    stored: { label: 'Stored', note: 'File reached its destination', progress: 100 },
};
const nodeNames = {
    node1: 'Node 1 · Hot',
    node2: 'Node 2 · Warm',
    node3: 'Node 3 · Cold',
};
let activePipelineId = null;
let activePipelineStarted = 0;
let stageQueue = [];
let stageAnimating = false;
let stageTimer = null;

function nodeLabel(nodeId, nodeName = '') {
    return nodeName || nodeNames[nodeId] || nodeId || '—';
}

function fileSlot(nodeId) {
    if (!nodeId || !['node1', 'node2', 'node3'].includes(nodeId)) return null;
    return $(`[data-node-anchor="${nodeId}"]`);
}

function positionPacket(target) {
    const canvas = $('#pipelineCanvas');
    const packet = $('#filePacket');
    if (!target) return;
    const canvasRect = canvas.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    packet.style.left = `${targetRect.left - canvasRect.left + targetRect.width / 2}px`;
    packet.style.top = `${targetRect.top - canvasRect.top + targetRect.height / 2}px`;
    packet.classList.add('visible');
}

function positionPacketBetween(start, end, ratio) {
    if (!start || !end) return;
    const canvas = $('#pipelineCanvas').getBoundingClientRect();
    const from = start.getBoundingClientRect();
    const to = end.getBoundingClientRect();
    const fromX = from.left + from.width / 2 - canvas.left;
    const fromY = from.top + from.height / 2 - canvas.top;
    const toX = to.left + to.width / 2 - canvas.left;
    const toY = to.top + to.height / 2 - canvas.top;
    const packet = $('#filePacket');
    packet.style.left = `${fromX + (toX - fromX) * ratio}px`;
    packet.style.top = `${fromY + (toY - fromY) * ratio}px`;
    packet.classList.add('visible');
}

function resetPipeline() {
    clearTimeout(stageTimer);
    stageQueue = [];
    stageAnimating = false;
    $$('.node-card').forEach((node) => node.classList.remove('active', 'done', 'target', 'moving', 'stored', 'failed'));
}

function beginPipeline(payload) {
    resetPipeline();
    const packet = $('#filePacket');
    packet.classList.remove('idle', 'failed');
    packet.classList.remove('visible');
    packet.style.transition = 'none';
    packet.textContent = 'FILE';
    packet.title = payload.filename || 'Uploaded file';
    $('#activeFilename').textContent = payload.filename || 'Uploaded file';
    $('#activeFileMeta').textContent = `${formatBytes(payload.file_size)} · ${payload.source === 'user' ? 'User upload' : 'Admin upload'}`;
    $('#activeStageLabel').textContent = 'Upload received';
    $('#activeStageNote').textContent = 'File arrived from the user';
    $('#activeProgress').style.width = '0%';
    $('#receivedDetail').textContent = 'File received';
    $('#modelDetail').textContent = 'Metadata → Random Forest';
    $('#placementDetail').textContent = 'Placement controller is waiting for a model prediction.';
    positionPacket($('#userLane'));
    packet.offsetWidth;
    packet.style.removeProperty('transition');
}

function updateModelDecision(payload) {
    const tier = String(payload.tier || payload.predicted_popularity || '').toLowerCase();
    const confidence = Number(payload.confidence);
    $('#modelDetail').textContent = tier
        ? `${tier.toUpperCase()} prediction · ${Number.isFinite(confidence) ? `${(confidence * 100).toFixed(1)}% confidence` : 'confidence unavailable'}`
        : 'Random Forest prediction';
}

function showStage(payload) {
    const index = stageOrder.indexOf(payload.stage);
    if (index < 0) return;
    const info = stageDetails[payload.stage];
    const user = $('#stageReceived');
    const model = $('#stageModel');
    const targetNode = payload.target_node ? $(`.node-storage[data-node="${payload.target_node}"]`) : null;
    const slot = fileSlot(payload.target_node);

    $$('.node-card').forEach((node) => node.classList.remove('active', 'done', 'target', 'moving', 'stored', 'failed'));
    if (index > 0) user.classList.add('done');
    if (index > 2) model.classList.add('done');

    if (['received'].includes(payload.stage)) user.classList.add('active');
    else if (['metadata', 'model'].includes(payload.stage)) model.classList.add('active');
    else if (targetNode) targetNode.classList.add('active');

    if (payload.stage === 'metadata') {
        $('#modelDetail').textContent = `${formatBytes(payload.file_size)} · reading metadata`;
        positionPacketBetween($('#userLane'), $('#modelInLane'), 0.55);
    } else if (payload.stage === 'model') {
        updateModelDecision(payload);
        positionPacket($('#modelLane'));
    } else if (payload.stage === 'placement') {
        const targetName = nodeLabel(payload.target_node, payload.target_node_name);
        $('#placementDetail').textContent = `Placement controller selected ${targetName}.`;
        if (targetNode) targetNode.classList.add('target');
        positionPacketBetween($('#modelLane'), slot || $('#modelLane'), 0.45);
        updateModelDecision(payload);
    } else if (payload.stage === 'storing' || payload.stage === 'stored') {
        const node = targetNode;
        if (node) node.classList.add(payload.stage === 'stored' ? 'stored' : 'moving');
        $('#placementDetail').textContent = `${payload.stage === 'stored' ? 'File stored on' : 'Sending file to'} ${nodeLabel(payload.target_node, payload.target_node_name)}.`;
        positionPacket(slot || targetNode);
        updateModelDecision(payload);
    } else {
        positionPacket($('#userLane'));
    }

    $('#activeStageLabel').textContent = info.label;
    $('#activeStageNote').textContent = info.note;
    $('#activeProgress').style.width = `${info.progress}%`;
}

function showFailure(payload) {
    $$('.node-card').forEach((node) => node.classList.remove('active'));
    const node = payload.target_node ? $(`.node-storage[data-node="${payload.target_node}"]`) : null;
    if (node) node.classList.add('failed');
    $('#filePacket').classList.add('failed');
    $('#activeStageLabel').textContent = 'Upload failed';
    $('#activeStageNote').textContent = payload.error || 'Unable to place the file';
    $('#activeProgress').style.width = '0%';
    $('#placementDetail').textContent = payload.error || 'The file could not be placed.';
}

function playStageQueue() {
    if (stageAnimating || !stageQueue.length) return;
    const payload = stageQueue.shift();
    stageAnimating = true;
    if (payload.stage === 'failed') showFailure(payload);
    else showStage(payload);
    stageTimer = window.setTimeout(() => {
        stageAnimating = false;
        playStageQueue();
    }, 650);
}

function handlePipelineStage(payload) {
    const startedAt = Date.parse(payload.started_at || payload.timestamp) || Date.now();
    if (payload.stage === 'received') {
        if (startedAt < activePipelineStarted) return;
        activePipelineId = payload.pipeline_id || `upload-${startedAt}`;
        activePipelineStarted = startedAt;
        beginPipeline(payload);
    } else if (payload.pipeline_id && payload.pipeline_id !== activePipelineId) {
        return;
    }
    stageQueue.push(payload);
    playStageQueue();
}

function renderNodeCapacity(nodes) {
    (nodes || []).forEach((node) => {
        const capacity = Number(node.capacity_bytes || 0);
        const used = Number(node.used_bytes || 0);
        const utilization = capacity ? Math.min(100, used / capacity * 100) : 0;
        const option = $(`.node-storage[data-node="${node.node_id}"]`);
        if (!option) return;
        $('.node-info strong', option).textContent = node.name || nodeLabel(node.node_id);
        $('[data-node-util]', option).textContent = `${utilization.toFixed(0)}%`;
        $('[data-node-meter]', option).style.width = `${utilization.toFixed(1)}%`;
    });
}

async function refreshNodes() {
    try {
        const response = await fetch('/api/status');
        if (!response.ok) throw new Error('Unable to read storage node status');
        const status = await response.json();
        renderNodeCapacity(status.nodes || []);
    } catch (error) {
        // The live-feed badge is driven by the event stream, not this capacity refresh.
    }
}

const events = new EventSource('/api/events');
events.addEventListener('connected', () => setConnection(true));
events.addEventListener('pipeline_stage', (event) => {
    try { handlePipelineStage(JSON.parse(event.data)); }
    catch (error) { console.error('Invalid pipeline update', error); }
});
events.addEventListener('file_uploaded', () => refreshNodes());
events.onerror = () => setConnection(false);

positionPacket($('#userLane'));
prepareUserLink();
refreshNodes();
window.setInterval(refreshNodes, 15000);
window.addEventListener('resize', () => {
    const packet = $('#filePacket');
    if (packet.classList.contains('idle')) positionPacket($('#userLane'));
});
