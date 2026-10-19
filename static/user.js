// User Portal Client Script
let selectedFile = null;

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

// Init Drag & Drop
function initDropZone() {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('user-file-input');
    const pill = document.getElementById('selected-file-pill');
    const pillName = document.getElementById('selected-file-name');
    const pillSize = document.getElementById('selected-file-size');
    const btnRemove = document.getElementById('btn-remove-file');

    dropZone.addEventListener('click', (e) => {
        if (e.target !== btnRemove) {
            fileInput.click();
        }
    });

    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.add('dragover');
        });
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove('dragover');
        });
    });

    dropZone.addEventListener('drop', (e) => {
        if (e.dataTransfer.files.length) {
            handleFileSelection(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length) {
            handleFileSelection(fileInput.files[0]);
        }
    });

    btnRemove.addEventListener('click', (e) => {
        e.stopPropagation();
        selectedFile = null;
        fileInput.value = '';
        pill.classList.add('hidden');
    });

    function handleFileSelection(file) {
        selectedFile = file;
        pillName.textContent = file.name;
        pillSize.textContent = `(${formatBytes(file.size)})`;
        pill.classList.remove('hidden');
    }
}

// Handle File Upload Form Submission
function initUploadForm() {
    const form = document.getElementById('user-upload-form');
    const btnUpload = document.getElementById('btn-user-upload');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!selectedFile) {
            showToast('Please select or drop a file to upload', 'error');
            return;
        }

        const formData = new FormData();
        formData.append('file', selectedFile);
        formData.append('source', 'user');

        btnUpload.disabled = true;
        btnUpload.innerHTML = '<span class="spinner"></span> <span>Running ML Classification...</span>';

        try {
            const res = await fetch('/api/files', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();

            if (res.ok) {
                showToast(`🚀 File '${data.file.filename}' successfully placed on ${data.placement_decision.target_node_name}!`, 'success');
                displayPlacementResult(data);
            } else {
                showToast(data.error || 'Failed to place file', 'error');
            }
        } catch (err) {
            console.error('Upload error:', err);
            showToast('Network error during file upload', 'error');
        } finally {
            btnUpload.disabled = false;
            btnUpload.innerHTML = '<span class="btn-text">🚀 Upload file for ML placement</span>';
        }
    });
}

// Display Placement Result Card
function displayPlacementResult(data) {
    const card = document.getElementById('placement-result-card');
    const decision = data.placement_decision;
    const tier = decision.tier || 'unknown';

    document.getElementById('result-filename').textContent = `${data.file.filename} (${formatBytes(data.file.file_size)})`;
    document.getElementById('result-node').textContent = decision.target_node_name || decision.node_id;
    document.getElementById('result-confidence').textContent = `${Math.round((decision.confidence || 1.0) * 100)}%`;
    document.getElementById('result-latency').textContent = `~${decision.node_latency_ms || 25} ms`;
    document.getElementById('result-reason').textContent = decision.reason;

    const badge = document.getElementById('result-tier-badge');
    badge.className = `badge badge-${tier}`;
    badge.textContent = `${tier.toUpperCase()} TIER`;

    const icon = document.getElementById('result-tier-icon');
    icon.textContent = tier === 'hot' ? '🔥' : (tier === 'warm' ? '⚡' : '❄️');

    // Probability Bars
    const probs = decision.probabilities || { hot: 0, warm: 0, cold: 0 };
    const pHot = Math.round((probs.hot || 0) * 100);
    const pWarm = Math.round((probs.warm || 0) * 100);
    const pCold = Math.round((probs.cold || 0) * 100);

    const barHot = document.getElementById('prob-bar-hot');
    const barWarm = document.getElementById('prob-bar-warm');
    const barCold = document.getElementById('prob-bar-cold');

    barHot.style.width = `${Math.max(5, pHot)}%`;
    barHot.textContent = pHot > 12 ? `${pHot}%` : '';
    barWarm.style.width = `${Math.max(5, pWarm)}%`;
    barWarm.textContent = pWarm > 12 ? `${pWarm}%` : '';
    barCold.style.width = `${Math.max(5, pCold)}%`;
    barCold.textContent = pCold > 12 ? `${pCold}%` : '';

    document.getElementById('prob-label-hot').textContent = `Hot: ${pHot}%`;
    document.getElementById('prob-label-warm').textContent = `Warm: ${pWarm}%`;
    document.getElementById('prob-label-cold').textContent = `Cold: ${pCold}%`;

    card.classList.remove('hidden');
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    initDropZone();
    initUploadForm();
});
