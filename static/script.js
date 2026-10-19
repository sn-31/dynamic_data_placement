// Admin Dashboard Logic & Real-Time Placement Flow
let storageChart = null;
let latencyChart = null;
let lastPlacementEvent = null;
let eventSource = null;

// Utility: Format bytes
function formatBytes(bytes, decimals = 2) {
    if (!+bytes) return '0 B';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}

// Utility: Toast notifications
function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 4500);
}

// ========================================================
// 1. REAL-TIME SERVER-SENT EVENTS (SSE) LISTENER
// ========================================================
function initSSE() {
    const indicator = document.getElementById('sse-status-indicator');
    const statusText = document.getElementById('sse-status-text');

    if (eventSource) {
        eventSource.close();
    }

    eventSource = new EventSource('/api/events');

    eventSource.addEventListener('connected', (e) => {
        const data = JSON.parse(e.data);
        statusText.textContent = 'Live SSE Connected';
        indicator.querySelector('.pulse-dot').classList.add('active');
        console.log('[SSE] Connected to real-time telemetry stream:', data);
    });

    eventSource.addEventListener('file_uploaded', (e) => {
        const data = JSON.parse(e.data);
        console.log('[SSE] File uploaded event received:', data);
        
        // Trigger live visual animation
        triggerPlacementAnimation(data);

        // Update telemetry HUD
        updateTelemetryHUD(data);

        // Background refresh of stats and inventory
        fetchStatus();
        fetchFiles();

        const nodeName = data.target_node_name || data.target_node;
        showToast(`🚀 [Live Telemetry] '${data.filename}' placed on ${nodeName} (${(data.tier || 'unknown').toUpperCase()} tier) by ML Model`, 'success');
    });

    eventSource.addEventListener('file_accessed', (e) => {
        const data = JSON.parse(e.data);
        console.log('[SSE] File accessed event received:', data);
        
        // Trigger access animation
        triggerAccessAnimation(data);

        // Refresh stats and logs
        fetchStatus();
        fetchFiles();

        showToast(`⚡ [Live Access] '${data.filename}' read from ${data.node_id} in ${data.latency_ms} ms (Tier: ${(data.tier || 'unknown').toUpperCase()})`, 'info');
    });

    eventSource.addEventListener('file_migrated', (e) => {
        const data = JSON.parse(e.data);
        console.log('[SSE] File migrated event received:', data);
        
        triggerMigrationAnimation(data);
        fetchStatus();
        fetchFiles();

        showToast(`🔄 [Live Migration] '${data.filename}' dynamically promoted to ${data.to_node} (${data.to_tier.toUpperCase()})`, 'warning');
    });

    eventSource.addEventListener('file_deleted', (e) => {
        fetchStatus();
        fetchFiles();
    });

    eventSource.addEventListener('model_trained', (e) => {
        const data = JSON.parse(e.data);
        const acc = (data.accuracy * 100).toFixed(1);
        showToast(`🧠 [Live] ML Model retrained! Validation Accuracy: ${acc}%`, 'success');
    });

    eventSource.onerror = (err) => {
        statusText.textContent = 'Reconnecting SSE...';
        indicator.querySelector('.pulse-dot').classList.remove('active');
        console.warn('[SSE] Connection error. Browser will auto-retry.', err);
    };
}

// ========================================================
// 2. SVG DATA HIGHWAY PATH POSITIONING
// ========================================================
function updateSvgPaths() {
    const canvas = document.getElementById('flow-canvas');
    if (!canvas) return;

    const canvasRect = canvas.getBoundingClientRect();

    const clientNode = document.getElementById('node-viz-client');
    const aiNode = document.getElementById('node-viz-ai');
    const node1 = document.getElementById('node-viz-node1');
    const node2 = document.getElementById('node-viz-node2');
    const node3 = document.getElementById('node-viz-node3');

    if (!clientNode || !aiNode || !node1 || !node2 || !node3) return;

    const rClient = clientNode.getBoundingClientRect();
    const rAI = aiNode.getBoundingClientRect();
    const rNode1 = node1.getBoundingClientRect();
    const rNode2 = node2.getBoundingClientRect();
    const rNode3 = node3.getBoundingClientRect();

    // Coordinates relative to canvas
    const pClientRight = {
        x: rClient.right - canvasRect.left,
        y: rClient.top + rClient.height / 2 - canvasRect.top
    };

    const pAILeft = {
        x: rAI.left - canvasRect.left,
        y: rAI.top + rAI.height / 2 - canvasRect.top
    };

    const pAIRight = {
        x: rAI.right - canvasRect.left,
        y: rAI.top + rAI.height / 2 - canvasRect.top
    };

    const pNode1Left = {
        x: rNode1.left - canvasRect.left,
        y: rNode1.top + rNode1.height / 2 - canvasRect.top
    };

    const pNode2Left = {
        x: rNode2.left - canvasRect.left,
        y: rNode2.top + rNode2.height / 2 - canvasRect.top
    };

    const pNode3Left = {
        x: rNode3.left - canvasRect.left,
        y: rNode3.top + rNode3.height / 2 - canvasRect.top
    };

    // Helper: Build smooth cubic bezier curve
    function buildBezier(p1, p2) {
        const dx = (p2.x - p1.x) * 0.5;
        return `M ${p1.x} ${p1.y} C ${p1.x + dx} ${p1.y}, ${p2.x - dx} ${p2.y}, ${p2.x} ${p2.y}`;
    }

    document.getElementById('path-user-ai').setAttribute('d', buildBezier(pClientRight, pAILeft));
    document.getElementById('path-ai-hot').setAttribute('d', buildBezier(pAIRight, pNode1Left));
    document.getElementById('path-ai-warm').setAttribute('d', buildBezier(pAIRight, pNode2Left));
    document.getElementById('path-ai-cold').setAttribute('d', buildBezier(pAIRight, pNode3Left));
}

// ========================================================
// 3. REAL-TIME PLACEMENT FLOW ANIMATION (STAR FEATURE)
// ========================================================
function triggerPlacementAnimation(eventData) {
    lastPlacementEvent = eventData;
    const canvas = document.getElementById('flow-canvas');
    const packetContainer = document.getElementById('packet-container');
    if (!canvas || !packetContainer) return;

    updateSvgPaths();

    const clientNode = document.getElementById('node-viz-client');
    const aiNode = document.getElementById('node-viz-ai');
    const targetNodeId = eventData.target_node || 'node2';
    const targetNode = document.getElementById(`node-viz-${targetNodeId}`) || document.getElementById('node-viz-node2');

    const tier = eventData.tier || 'unknown';
    const filename = eventData.filename || 'something.txt';
    const sizeStr = formatBytes(eventData.file_size || 10240);

    // Client IP display
    const clientIpDisplay = document.getElementById('viz-client-ip');
    if (clientIpDisplay && eventData.client_ip) {
        clientIpDisplay.textContent = `Client: ${eventData.client_ip}`;
    }

    // Step 1: User Client lights up
    clientNode.classList.add('active-pulse');

    // Create floating packet
    const packet = document.createElement('div');
    packet.className = `flow-packet packet-${tier}`;
    packet.innerHTML = `<span>📄</span> <span>${filename}</span> <small>(${sizeStr})</small>`;
    packetContainer.appendChild(packet);

    const canvasRect = canvas.getBoundingClientRect();
    const rClient = clientNode.getBoundingClientRect();
    const rAI = aiNode.getBoundingClientRect();
    const rTarget = targetNode.getBoundingClientRect();

    const startX = rClient.right - canvasRect.left;
    const startY = rClient.top + rClient.height / 2 - canvasRect.top;

    const aiX = rAI.left + rAI.width / 2 - canvasRect.left;
    const aiY = rAI.top + rAI.height / 2 - canvasRect.top;

    const endX = rTarget.left + 25 - canvasRect.left;
    const endY = rTarget.top + rTarget.height / 2 - canvasRect.top;

    // Set initial position
    packet.style.left = `${startX}px`;
    packet.style.top = `${startY}px`;
    packet.style.transition = 'all 1.1s cubic-bezier(0.25, 1, 0.5, 1)';

    // Step 2: Animate packet to AI Node
    requestAnimationFrame(() => {
        packet.style.left = `${aiX}px`;
        packet.style.top = `${aiY}px`;
    });

    // Step 3: Arrive at AI Node (after 1.1s)
    setTimeout(() => {
        clientNode.classList.remove('active-pulse');
        aiNode.classList.add('active-evaluating');

        const aiStatus = document.getElementById('viz-ai-status');
        if (aiStatus) {
            aiStatus.textContent = `Evaluating Features: ${tier.toUpperCase()} (${Math.round((eventData.confidence || 1.0) * 100)}%)`;
        }

        // Update HUD during evaluation
        updateTelemetryHUD(eventData);

        // Step 4: After 0.6s processing, packet moves from AI to Target Node
        setTimeout(() => {
            packet.style.transition = 'all 1.1s cubic-bezier(0.25, 1, 0.5, 1)';
            packet.style.left = `${endX}px`;
            packet.style.top = `${endY}px`;

            // Step 5: Arrive at Target Node (after 1.1s)
            setTimeout(() => {
                aiNode.classList.remove('active-evaluating');
                if (aiStatus) {
                    aiStatus.textContent = 'Inference Engine Active';
                }

                targetNode.classList.add('highlight-target');

                // Animate mini bar
                const miniBar = document.getElementById(`viz-bar-${targetNodeId}`);
                if (miniBar) {
                    const curW = parseInt(miniBar.style.width || '20');
                    miniBar.style.width = `${Math.min(100, curW + 8)}%`;
                }

                // Fade out packet
                packet.style.transition = 'all 0.5s ease-out';
                packet.style.opacity = '0';
                packet.style.transform = 'translate(-50%, -50%) scale(1.4)';

                setTimeout(() => {
                    packet.remove();
                    targetNode.classList.remove('highlight-target');
                }, 1000);

            }, 1100);

        }, 600);

    }, 1100);
}

// Trigger Access Request Animation (User -> Storage Node and back)
function triggerAccessAnimation(data) {
    const canvas = document.getElementById('flow-canvas');
    const packetContainer = document.getElementById('packet-container');
    if (!canvas || !packetContainer) return;

    const clientNode = document.getElementById('node-viz-client');
    const targetNode = document.getElementById(`node-viz-${data.node_id}`) || document.getElementById('node-viz-node2');
    if (!clientNode || !targetNode) return;

    const canvasRect = canvas.getBoundingClientRect();
    const rClient = clientNode.getBoundingClientRect();
    const rTarget = targetNode.getBoundingClientRect();

    const startX = rClient.right - canvasRect.left;
    const startY = rClient.top + rClient.height / 2 - canvasRect.top;
    const endX = rTarget.left + 25 - canvasRect.left;
    const endY = rTarget.top + rTarget.height / 2 - canvasRect.top;

    const packet = document.createElement('div');
    packet.className = `flow-packet packet-${data.tier || 'unknown'}`;
    packet.innerHTML = `<span>⚡ READ:</span> <span>${data.filename}</span>`;
    packetContainer.appendChild(packet);

    packet.style.left = `${startX}px`;
    packet.style.top = `${startY}px`;
    packet.style.transition = 'all 0.6s ease-in-out';

    // Zip to target node
    requestAnimationFrame(() => {
        packet.style.left = `${endX}px`;
        packet.style.top = `${endY}px`;
    });

    // Flash node and return
    setTimeout(() => {
        targetNode.classList.add('highlight-target');
        packet.innerHTML = `<span>✅ ${data.latency_ms} ms</span>`;
        packet.style.left = `${startX}px`;
        packet.style.top = `${startY}px`;

        setTimeout(() => {
            targetNode.classList.remove('highlight-target');
            packet.style.opacity = '0';
            setTimeout(() => packet.remove(), 400);
        }, 600);
    }, 600);
}

// Trigger Dynamic Migration Animation (Node -> Node)
function triggerMigrationAnimation(data) {
    const canvas = document.getElementById('flow-canvas');
    const packetContainer = document.getElementById('packet-container');
    if (!canvas || !packetContainer) return;

    const fromNode = document.getElementById(`node-viz-${data.from_node}`);
    const toNode = document.getElementById(`node-viz-${data.to_node}`);
    if (!fromNode || !toNode) return;

    const canvasRect = canvas.getBoundingClientRect();
    const rFrom = fromNode.getBoundingClientRect();
    const rTo = toNode.getBoundingClientRect();

    const startX = rFrom.left + rFrom.width / 2 - canvasRect.left;
    const startY = rFrom.top + rFrom.height / 2 - canvasRect.top;
    const endX = rTo.left + rTo.width / 2 - canvasRect.left;
    const endY = rTo.top + rTo.height / 2 - canvasRect.top;

    const packet = document.createElement('div');
    packet.className = `flow-packet packet-${data.to_tier || 'hot'}`;
    packet.innerHTML = `<span>🔄 MIGRATE:</span> <span>${data.filename}</span>`;
    packetContainer.appendChild(packet);

    packet.style.left = `${startX}px`;
    packet.style.top = `${startY}px`;
    packet.style.transition = 'all 1.0s cubic-bezier(0.25, 1, 0.5, 1)';

    fromNode.classList.add('highlight-target');

    requestAnimationFrame(() => {
        packet.style.left = `${endX}px`;
        packet.style.top = `${endY}px`;
    });

    setTimeout(() => {
        fromNode.classList.remove('highlight-target');
        toNode.classList.add('highlight-target');
        setTimeout(() => {
            toNode.classList.remove('highlight-target');
            packet.remove();
        }, 800);
    }, 1000);
}

// Update Telemetry HUD
function updateTelemetryHUD(data) {
    const hud = document.getElementById('telemetry-hud');
    if (!hud) return;

    const filename = data.filename || 'sample_file.txt';
    const tier = data.tier || data.predicted_popularity || 'unknown';
    const conf = Math.round((data.confidence || 1.0) * 100);
    const target = data.target_node_name || data.target_node || 'Node 2';

    document.getElementById('hud-filename').textContent = `${filename} (${formatBytes(data.file_size || 5120)})`;

    const tierBadge = document.getElementById('hud-tier-val');
    tierBadge.innerHTML = `<span class="badge badge-${tier}">${tier.toUpperCase()} TIER</span>`;

    document.getElementById('hud-target-val').textContent = target;
    document.getElementById('hud-conf-val').textContent = `${conf}%`;

    const probs = data.probabilities || {};
    const pHot = Math.round((probs.hot || 0) * 100);
    const pWarm = Math.round((probs.warm || 0) * 100);
    const pCold = Math.round((probs.cold || 0) * 100);

    const probVal = document.getElementById('hud-prob-val');
    if (probs.hot !== undefined) {
        probVal.textContent = `Hot: ${pHot}% | Warm: ${pWarm}% | Cold: ${pCold}%`;
    } else {
        probVal.textContent = `Evaluated by Random Forest Classifier`;
    }
}

// ========================================================
// 4. FETCH STATUS & RENDER METRICS
// ========================================================
async function fetchStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();

        // Update Summary Cards
        document.getElementById('metric-total-files').textContent = data.summary.total_files;
        document.getElementById('metric-total-size').textContent = `${formatBytes(data.summary.total_used_bytes)} total`;
        document.getElementById('metric-total-accesses').textContent = data.summary.total_access_logs;
        document.getElementById('metric-avg-latency').textContent = `${data.summary.avg_latency_ms} ms`;

        // Render Nodes Grid
        renderNodes(data.nodes);

        // Render Recent Logs
        renderLogs(data.recent_logs);

        // Update Charts
        updateCharts(data.nodes);
    } catch (err) {
        console.error('Error fetching status:', err);
    }
}

// Render Storage Node Cards
function renderNodes(nodes) {
    const grid = document.getElementById('nodes-grid');
    if (!grid) return;
    grid.innerHTML = '';

    nodes.forEach(node => {
        const card = document.createElement('div');
        card.className = `card node-card tier-${node.tier}`;

        const pct = node.utilization_pct || 0;
        const barColor = node.tier === 'hot' ? '#ef4444' : (node.tier === 'warm' ? '#f59e0b' : '#06b6d4');

        card.innerHTML = `
            <div class="node-header">
                <div>
                    <h3 class="node-title">${node.name}</h3>
                    <span class="node-meta">Latency: ~${node.base_latency_ms} ms | ${node.file_count || 0} files</span>
                </div>
                <span class="badge badge-${node.tier}">${node.tier}</span>
            </div>
            <div class="progress-container">
                <div class="progress-bar" style="width: ${pct}%; background-color: ${barColor}"></div>
            </div>
            <div class="node-stats">
                <span>${pct}% used</span>
                <span>${formatBytes(node.used_bytes)} / ${formatBytes(node.capacity_bytes)}</span>
            </div>
        `;
        grid.appendChild(card);

        // Also update mini bar in flow visualizer
        const miniBar = document.getElementById(`viz-bar-${node.node_id}`);
        if (miniBar) {
            miniBar.style.width = `${Math.max(5, pct)}%`;
        }
    });
}

// Fetch and render stored files
async function fetchFiles() {
    try {
        const res = await fetch('/api/files');
        const data = await res.json();
        const tbody = document.getElementById('files-tbody');
        if (!tbody) return;

        if (!data.files || data.files.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-center">No files in storage. Upload a file or click "Seed Demo Files".</td></tr>`;
            return;
        }

        tbody.innerHTML = '';
        data.files.forEach(f => {
            const tr = document.createElement('tr');
            const avgLat = f.avg_latency_ms ? `${parseFloat(f.avg_latency_ms).toFixed(1)} ms` : '-';
            const popBadge = `<span class="badge badge-${f.predicted_popularity || 'unknown'}">${f.predicted_popularity || 'unknown'}</span>`;

            tr.innerHTML = `
                <td><strong>${f.filename}</strong></td>
                <td>${formatBytes(f.file_size)}</td>
                <td>${f.node_name || f.current_node_id}</td>
                <td>${f.access_count}</td>
                <td>${avgLat}</td>
                <td>${popBadge}</td>
                <td><span class="badge badge-accent">ML (Random Forest)</span></td>
                <td>
                    <div class="actions-cell">
                        <button class="btn btn-sm btn-access" onclick="simulateAccess(${f.file_id})">⚡ Read</button>
                        <a href="/api/files/${f.file_id}/download" class="btn btn-sm btn-secondary" download title="Download">⬇️</a>
                        <button class="btn btn-sm btn-danger" onclick="deleteFile(${f.file_id})">🗑️</button>
                    </div>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error('Error fetching files:', err);
    }
}

// Render Recent Access Logs
function renderLogs(logs) {
    const tbody = document.getElementById('logs-tbody');
    if (!tbody) return;
    if (!logs || logs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center">No access logs yet.</td></tr>`;
        return;
    }

    tbody.innerHTML = '';
    logs.slice(0, 10).forEach(log => {
        const tr = document.createElement('tr');
        const timeStr = new Date(log.accessed_at).toLocaleTimeString();
        tr.innerHTML = `
            <td>${timeStr}</td>
            <td><strong>${log.filename}</strong></td>
            <td>${log.node_id}</td>
            <td><span class="badge badge-${log.node_tier}">${log.node_tier}</span></td>
            <td><strong>${log.response_time_ms} ms</strong></td>
            <td><code>${log.access_type}</code></td>
        `;
        tbody.appendChild(tr);
    });
}

// Update Chart.js Charts
function updateCharts(nodes) {
    const canvasStorage = document.getElementById('chart-storage');
    const canvasLatency = document.getElementById('chart-latency');
    if (!canvasStorage || !canvasLatency) return;

    const labels = nodes.map(n => n.name.split(' (')[0].replace('Node ', 'N'));
    const usedMB = nodes.map(n => (n.used_bytes / (1024 * 1024)).toFixed(2));
    const latencies = nodes.map(n => n.base_latency_ms);
    const colors = ['#ef4444', '#f59e0b', '#06b6d4'];

    // 1. Storage Distribution Chart
    const ctxStorage = canvasStorage.getContext('2d');
    if (storageChart) {
        storageChart.data.labels = labels;
        storageChart.data.datasets[0].data = usedMB;
        storageChart.update();
    } else {
        storageChart = new Chart(ctxStorage, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: usedMB,
                    backgroundColor: colors,
                    borderColor: '#131c31',
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'bottom', labels: { color: '#94a3b8' } }
                }
            }
        });
    }

    // 2. Latency Chart
    const ctxLatency = canvasLatency.getContext('2d');
    if (latencyChart) {
        latencyChart.data.labels = labels;
        latencyChart.data.datasets[0].data = latencies;
        latencyChart.update();
    } else {
        latencyChart = new Chart(ctxLatency, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Base Latency (ms)',
                    data: latencies,
                    backgroundColor: colors,
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { ticks: { color: '#94a3b8' } },
                    y: { ticks: { color: '#94a3b8' }, beginAtZero: true }
                },
                plugins: {
                    legend: { display: false }
                }
            }
        });
    }
}

// Simulate File Access
async function simulateAccess(fileId) {
    try {
        const res = await fetch(`/api/files/${fileId}/access`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showToast(`Read from ${data.current_node} in ${data.latency_ms} ms! (ML Popularity: ${data.new_predicted_popularity.toUpperCase()})`, 'success');
        } else {
            showToast(data.error || 'Failed to read file', 'error');
        }
    } catch (err) {
        showToast('Error during file read request', 'error');
    }
}

// Delete File
async function deleteFile(fileId) {
    if (!confirm('Are you sure you want to delete this file?')) return;
    try {
        const res = await fetch(`/api/files/${fileId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('File deleted successfully', 'success');
        }
    } catch (err) {
        showToast('Error deleting file', 'error');
    }
}

// Admin Direct Upload Handler
const uploadForm = document.getElementById('upload-form');
if (uploadForm) {
    uploadForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const fileInput = document.getElementById('file-input');

        if (!fileInput.files.length) return;

        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('source', 'admin');

        const btn = document.getElementById('btn-upload');
        btn.disabled = true;
        btn.textContent = 'Evaluating ML Placement...';

        try {
            const res = await fetch('/api/files', { method: 'POST', body: formData });
            const data = await res.json();
            if (res.ok) {
                fileInput.value = '';
            } else {
                showToast(data.error || 'Upload failed', 'error');
            }
        } catch (err) {
            showToast('Error uploading file', 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Upload & Place via ML';
        }
    });
}

// Copy URL Button
const btnCopy = document.getElementById('btn-copy-url');
if (btnCopy) {
    btnCopy.addEventListener('click', () => {
        const url = document.getElementById('user-portal-url').textContent.trim();
        navigator.clipboard.writeText(url).then(() => {
            showToast('📋 User portal URL copied to clipboard!', 'info');
        }).catch(() => {
            showToast(`Portal URL: ${url}`, 'info');
        });
    });
}

// Replay Animation Button
const btnReplay = document.getElementById('btn-replay-flow');
if (btnReplay) {
    btnReplay.addEventListener('click', () => {
        if (lastPlacementEvent) {
            showToast(`🎬 Replaying placement animation for '${lastPlacementEvent.filename}'`, 'info');
            triggerPlacementAnimation(lastPlacementEvent);
        } else {
            showToast('No recent upload event to replay. Upload a file first.', 'warning');
        }
    });
}

// Button: Seed Demo Files
const btnSeed = document.getElementById('btn-seed');
if (btnSeed) {
    btnSeed.addEventListener('click', async () => {
        showToast('Seeding demonstration files and realistic ML workload...', 'warning');
        try {
            const res = await fetch('/api/seed-demo', { method: 'POST' });
            const data = await res.json();
            if (res.ok) {
                showToast(data.message, 'success');
                fetchStatus();
                fetchFiles();
            }
        } catch (err) {
            showToast('Failed to seed demo data', 'error');
        }
    });
}

// Button: Retrain ML Model
const btnTrain = document.getElementById('btn-train');
if (btnTrain) {
    btnTrain.addEventListener('click', async () => {
        showToast('Training Random Forest model on historical access patterns...', 'warning');
        try {
            const res = await fetch('/api/train', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ use_synthetic: true })
            });
            const data = await res.json();
            if (res.ok) {
                const acc = (data.metrics.accuracy * 100).toFixed(2);
                showToast(`ML Model Retrained! Validation Accuracy: ${acc}%`, 'success');
            }
        } catch (err) {
            showToast('Model training failed', 'error');
        }
    });
}

// Button: Dynamic Migration
const btnMigrate = document.getElementById('btn-migrate');
if (btnMigrate) {
    btnMigrate.addEventListener('click', async () => {
        showToast('Evaluating file popularity & executing dynamic migrations via ML...', 'warning');
        try {
            const res = await fetch('/api/migrate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ policy: 'ml' })
            });
            const data = await res.json();
            if (res.ok) {
                showToast(`ML Evaluated ${data.total_files_evaluated} files. Migrated ${data.migrations_performed} files!`, 'success');
                fetchStatus();
                fetchFiles();
            }
        } catch (err) {
            showToast('Migration process failed', 'error');
        }
    });
}

// Button: Benchmark
const btnBenchmark = document.getElementById('btn-benchmark');
if (btnBenchmark) {
    btnBenchmark.addEventListener('click', async () => {
        showToast('Running Zipfian workload benchmark (50 simulated requests)...', 'warning');
        try {
            const res = await fetch('/api/benchmark', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ requests: 50 })
            });
            const data = await res.json();
            if (res.ok && !data.error) {
                showToast(`Benchmark Complete! Avg Latency: ${data.avg_latency_ms} ms (Min: ${data.min_latency_ms}ms, Max: ${data.max_latency_ms}ms)`, 'success');
                fetchStatus();
                fetchFiles();
            } else {
                showToast(data.error || 'Benchmark failed', 'error');
            }
        } catch (err) {
            showToast('Benchmark execution failed', 'error');
        }
    });
}

// Refresh button
const btnRefresh = document.getElementById('btn-refresh');
if (btnRefresh) {
    btnRefresh.addEventListener('click', () => {
        fetchStatus();
        fetchFiles();
        showToast('System metrics refreshed', 'info');
    });
}

// Window resize updates SVG paths
window.addEventListener('resize', updateSvgPaths);

// Initial bootstrap
document.addEventListener('DOMContentLoaded', () => {
    initSSE();
    fetchStatus();
    fetchFiles();
    setTimeout(updateSvgPaths, 300);
});
