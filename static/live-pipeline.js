(() => {
    const $ = (selector, root = document) => root.querySelector(selector);
    const formatBytes = (bytes) => {
        const value = Number(bytes || 0);
        if (!value) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
        return `${(value / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
    };
    const stagePanel = $('#page-transfer');
    const stageCanvas = $('#networkStage');
    if (!stagePanel || !stageCanvas || !window.EventSource) return;

    const fileTable = $('#fileTable');
    const marker = document.createElement('span');
    marker.className = 'live-file-marker';
    marker.textContent = '▤';
    marker.setAttribute('aria-label', 'File moving through the live pipeline');
    stageCanvas.appendChild(marker);

    const liveStyles = document.createElement('style');
    liveStyles.textContent = `
      .live-file-marker{position:absolute;z-index:5;left:50%;top:20%;display:grid;place-items:center;width:30px;height:30px;border:2px solid white;border-radius:50%;background:var(--blue);color:white;font-size:15px;font-weight:800;box-shadow:0 3px 12px #14254155;opacity:0;transform:translate(-50%,-50%);transition:left .65s ease,top .65s ease,opacity .2s ease;pointer-events:none}
      .live-file-marker.visible{opacity:1}.live-file-marker.failed{background:var(--red)}
    `;
    document.head.appendChild(liveStyles);

    // The HTML's built-in simulator is only a visual prototype. Keep its layout,
    // but turn its controls into a live view driven by the server's real events.
    const transferHeading = stagePanel.querySelector('.section-head h2');
    if (transferHeading) transferHeading.textContent = 'Live upload pipeline';
    const transferSubheading = stagePanel.querySelector('.section-head span');
    if (transferSubheading) transferSubheading.textContent = 'Actual user uploads · ML placement · storage destination';
    const cards = $('#transferSimulator')?.querySelectorAll(':scope > .card');
    if (cards?.[1]) {
        const cardHeading = cards[1].querySelector('.card-head h3');
        const cardDescription = cards[1].querySelector('.card-head p');
        if (cardHeading) cardHeading.textContent = 'Latest user upload';
        if (cardDescription) cardDescription.textContent = 'Live progress reported by the upload service';
        const controls = cards[1].querySelector('.sim-controls');
        if (controls) controls.hidden = true;
        const buttons = cards[1].querySelector('#startTransfer')?.parentElement;
        if (buttons) buttons.hidden = true;
    }

    // Stop the decorative demo packets; the marker below follows server events.
    stageCanvas.querySelectorAll('.packet').forEach((packet) => {
        packet.style.animation = 'none';
        packet.style.opacity = '0';
    });

    const nodeElements = {
        node1: { card: $('#nodeCardA'), status: $('#nodeAStatus'), label: 'Hot · SSD' },
        node2: { card: $('#nodeCardB'), status: $('#nodeBStatus'), label: 'Warm · Standard SSD' },
        node3: { card: $('#nodeCardC'), status: $('#nodeCStatus'), label: 'Cold · HDD archive' },
    };
    const stageInfo = {
        received: { label: 'Upload received', progress: 8 },
        metadata: { label: 'Reading metadata', progress: 26 },
        model: { label: 'ML prediction', progress: 48 },
        placement: { label: 'Choosing storage node', progress: 68 },
        storing: { label: 'Writing file to node', progress: 88 },
        stored: { label: 'Stored', progress: 100 },
    };
    const stageNames = Object.keys(stageInfo);
    let activePipelineId = null;
    let queue = [];
    let playing = false;
    let timer = null;
    let uploadInProgress = false;
    let currentFilename = '';

    function setConnection(connected) {
        const status = $('.topbar .status-pill');
        if (status) {
            const dot = status.querySelector('.dot');
            status.textContent = connected ? 'Live · Connected' : 'Live · Reconnecting';
            if (dot) status.prepend(dot);
        }
        const updated = $('#updatedLabel');
        if (updated && !uploadInProgress) {
            updated.textContent = connected ? 'Live upload feed · waiting for user upload' : 'Live upload feed · reconnecting';
        }
        $('#networkStatus').textContent = connected ? 'Live · Ready' : 'Reconnecting';
    }

    function moveMarker(target, fraction = 1) {
        if (!target) return;
        const canvasRect = stageCanvas.getBoundingClientRect();
        const targetRect = target.getBoundingClientRect();
        const x = targetRect.left - canvasRect.left + targetRect.width / 2;
        const y = targetRect.top - canvasRect.top + targetRect.height / 2;
        marker.style.left = `${x}px`;
        marker.style.top = `${y}px`;
        marker.classList.add('visible');
    }

    function moveMarkerBetween(start, end, fraction) {
        if (!start || !end) return moveMarker(end || start);
        const canvasRect = stageCanvas.getBoundingClientRect();
        const a = start.getBoundingClientRect();
        const b = end.getBoundingClientRect();
        const ax = a.left - canvasRect.left + a.width / 2;
        const ay = a.top - canvasRect.top + a.height / 2;
        const bx = b.left - canvasRect.left + b.width / 2;
        const by = b.top - canvasRect.top + b.height / 2;
        marker.style.left = `${ax + (bx - ax) * fraction}px`;
        marker.style.top = `${ay + (by - ay) * fraction}px`;
        marker.classList.add('visible');
    }

    function addLog(title, description) {
        const log = $('#transferLog');
        if (!log) return;
        const row = document.createElement('div');
        row.className = 'transfer-log-item';
        const bullet = document.createElement('span');
        bullet.textContent = '●';
        const text = document.createElement('div');
        const heading = document.createElement('b');
        heading.textContent = title;
        text.append(heading, document.createElement('br'), document.createTextNode(description));
        row.append(bullet, text);
        log.prepend(row);
        while (log.children.length > 8) log.lastElementChild.remove();
    }

    function setNodeTarget(nodeId, state) {
        Object.values(nodeElements).forEach(({ card, status, label }) => {
            if (card) card.classList.remove('node-active');
            if (status) status.textContent = label;
        });
        const target = nodeElements[nodeId];
        if (target) {
            target.card?.classList.add('node-active');
            if (target.status) target.status.textContent = state;
        }
        return target?.card || null;
    }

    function progress(stage, note) {
        const info = stageInfo[stage];
        if (!info) return;
        $('#networkStatus').textContent = info.label;
        $('#transferTitle').textContent = currentFilename || 'Latest user upload';
        $('#transferDescription').textContent = note;
        $('#transferProgress').style.width = `${info.progress}%`;
        $('#transferPercent').textContent = `Pipeline stage ${stageNames.indexOf(stage) + 1} of ${stageNames.length}`;
        const label = stagePanel.querySelector('.card-head h3');
        if (label) label.textContent = 'Latest user upload';
    }

    function beginUpload(payload) {
        activePipelineId = payload.pipeline_id || null;
        uploadInProgress = true;
        currentFilename = payload.filename || 'New upload';
        clearTimeout(timer);
        queue = [];
        playing = false;
        marker.classList.remove('failed');
        Object.values(nodeElements).forEach(({ card }) => card?.classList.remove('node-active'));
        $('#transferLog').replaceChildren();
        $('#ingestLabel').textContent = currentFilename;
        $('.node-meta small').textContent = 'Waiting for metadata';
        $('#transferTitle').textContent = currentFilename;
        $('#transferDescription').textContent = `${formatBytes(payload.file_size)} · received from user`;
        $('#transferProgress').style.width = '0%';
        $('#transferPercent').textContent = 'Pipeline starting';
        $('#networkStatus').textContent = 'Upload received';
        const receivedAt = $('#updatedLabel');
        if (receivedAt) receivedAt.textContent = `Live upload · ${payload.filename || 'file received'}`;
        moveMarker($('.node-ingest'));
        addLog('Upload received', `${payload.filename || 'File'} · ${formatBytes(payload.file_size)} · user upload`);
        stagePanel.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    function renderStage(payload) {
        const { stage, filename, file_size: size, target_node: nodeId, target_node_name: nodeName } = payload;
        const name = filename || $('#ingestLabel').textContent;
        const meta = $('.node-meta small');
        const nodeCard = nodeId ? nodeElements[nodeId]?.card : null;
        const tier = String(payload.tier || payload.predicted_popularity || '').toUpperCase();
        const confidence = Number(payload.confidence);
        const confidenceText = Number.isFinite(confidence) ? ` · ${(confidence * 100).toFixed(1)}% confidence` : '';
        let note = '';

        if (stage === 'received') {
            note = `${name} received from the user (${formatBytes(size)}).`;
            moveMarker($('.node-ingest'));
        } else if (stage === 'metadata') {
            note = `File size measured: ${formatBytes(size)}. Preparing model input.`;
            if (meta) meta.textContent = `${formatBytes(size)} · metadata ready`;
            moveMarkerBetween($('.node-ingest'), $('.node-meta'), 0.7);
        } else if (stage === 'model') {
            note = tier ? `Random Forest prediction: ${tier}${confidenceText}.` : 'Random Forest is predicting the file class.';
            if (meta) meta.textContent = tier ? `${tier} prediction${confidenceText}` : 'Random Forest prediction';
            moveMarker($('.node-meta'));
        } else if (stage === 'placement') {
            note = `Placement controller selected ${nodeName || nodeId || 'a storage node'} from the ML prediction.`;
            if (nodeCard) nodeCard.classList.add('node-active');
            moveMarkerBetween($('.node-meta'), nodeCard || $('.node-meta'), 0.65);
        } else if (stage === 'storing') {
            note = `Writing ${name} to ${nodeName || nodeId || 'the selected node'}.`;
            if (nodeCard) nodeCard.classList.add('node-active');
            moveMarkerBetween($('.node-meta'), nodeCard || $('.node-meta'), 0.9);
        } else if (stage === 'stored') {
            uploadInProgress = false;
            note = `${name} stored on ${nodeName || nodeId || 'the selected node'}.`;
            const target = setNodeTarget(nodeId, `Stored · ${tier || 'placed'}`);
            moveMarker(target || nodeCard || $('.node-meta'));
            const updated = $('#updatedLabel');
            if (updated) updated.textContent = `Live upload complete · ${name} → ${nodeName || nodeId}`;
            refreshFiles();
            refreshNodes();
        } else if (stage === 'failed') {
            uploadInProgress = false;
            marker.classList.add('failed');
            note = payload.error || 'The upload or placement failed.';
        } else {
            return;
        }

        progress(stage, note);
        if (stage === 'failed') {
            $('#networkStatus').textContent = 'Upload failed';
            $('#transferTitle').textContent = `${name} · failed`;
            $('#transferDescription').textContent = note;
            $('#transferProgress').style.width = '0%';
            $('#transferPercent').textContent = 'Upload failed';
            addLog('Upload failed', note);
        } else {
            addLog(stageInfo[stage].label, note);
        }
    }

    function playQueue() {
        if (playing || queue.length === 0) return;
        playing = true;
        const payload = queue.shift();
        renderStage(payload);
        timer = window.setTimeout(() => {
            playing = false;
            playQueue();
        }, 650);
    }

    function handlePipelineStage(payload) {
        if (payload.stage === 'received') beginUpload(payload);
        else if (payload.pipeline_id && payload.pipeline_id !== activePipelineId) return;
        queue.push(payload);
        playQueue();
    }

    function renderFiles(files) {
        if (!fileTable) return;
        fileTable.replaceChildren();
        if (!files.length) {
            const row = fileTable.insertRow();
            const cell = row.insertCell();
            cell.colSpan = 5;
            cell.textContent = 'No user uploads yet.';
            return;
        }
        files.forEach((file) => {
            const row = fileTable.insertRow();
            const nameCell = row.insertCell();
            const fileName = document.createElement('span');
            fileName.className = 'file-name';
            const icon = document.createElement('span');
            icon.className = 'file-ico';
            icon.textContent = '▤';
            fileName.append(icon, document.createTextNode(file.filename || 'Untitled file'));
            nameCell.append(fileName);

            row.insertCell().textContent = String(file.predicted_popularity || 'unclassified').toUpperCase();
            const tierCell = row.insertCell();
            const tier = String(file.predicted_popularity || 'cold').toLowerCase();
            const tag = document.createElement('span');
            tag.className = `tag ${tier === 'hot' ? 'hot' : tier === 'warm' ? 'warm' : 'archive'}`;
            tag.textContent = `${tier.toUpperCase()} · ${file.current_node_id || 'node unknown'}`;
            tierCell.append(tag);
            row.insertCell().textContent = '1';
            row.insertCell().textContent = `Stored on ${file.current_node_id || '—'}`;
        });
    }

    async function refreshFiles() {
        try {
            const response = await fetch('/api/files');
            if (!response.ok) return;
            const data = await response.json();
            renderFiles(data.files || []);
        } catch (error) {
            // Keep the live pipeline usable if the file list is temporarily unavailable.
        }
    }

    async function refreshNodes() {
        try {
            const response = await fetch('/api/status');
            if (!response.ok) return;
            const data = await response.json();
            (data.nodes || []).forEach((node) => {
                const target = nodeElements[node.node_id];
                if (!target) return;
                const strong = target.card?.querySelector('strong');
                if (strong) strong.textContent = node.name || strong.textContent;
                if (!target.card?.classList.contains('node-active') && target.status) {
                    const used = formatBytes(node.used_bytes);
                    const capacity = formatBytes(node.capacity_bytes);
                    target.status.textContent = `${used} / ${capacity}`;
                }
            });
        } catch (error) {
            // Capacity labels are supplemental; the event stream carries transfers.
        }
    }

    const events = new EventSource('/api/events');
    events.addEventListener('connected', () => setConnection(true));
    events.addEventListener('pipeline_stage', (event) => {
        try { handlePipelineStage(JSON.parse(event.data)); }
        catch (error) { console.error('Invalid pipeline event', error); }
    });
    events.addEventListener('file_uploaded', () => {
        refreshFiles();
        refreshNodes();
    });
    events.addEventListener('file_migrated', (event) => {
        try {
            const migration = JSON.parse(event.data);
            addLog('File migrated after access', `${migration.filename} · ${migration.from_node} → ${migration.to_node}`);
            refreshFiles();
            refreshNodes();
        } catch (error) {
            console.error('Invalid migration event', error);
        }
    });
    events.onerror = () => setConnection(false);

    $('#transferTitle').textContent = 'Waiting for a user upload';
    $('#transferDescription').textContent = 'A real upload will appear here as the server processes it through metadata, ML prediction, placement, and storage.';
    $('#transferPercent').textContent = 'Waiting for upload';
    $('#transferLog').replaceChildren();
    addLog('Live pipeline ready', 'Waiting for a user upload.');
    const meta = $('.node-meta small');
    if (meta) meta.textContent = 'Waiting for file metadata';
    Object.values(nodeElements).forEach(({ card }) => card?.classList.remove('node-active'));
    const updated = $('#updatedLabel');
    if (updated) updated.textContent = 'Live upload feed · connecting to server';
    refreshFiles();
    refreshNodes();
})();
