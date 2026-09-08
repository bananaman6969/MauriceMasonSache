// Shorts Stealth Pipeline Client Application
let currentTab = 'results';
let discoveredVideos = [];
let processedVideos = [];

// Initialize EventSource for SSE live progress updates
function initEventSource() {
    const eventSource = new EventSource('/api/events');

    eventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handlePipelineEvent(data);
        } catch (e) {
            // ignore non-json keepalives
        }
    };

    eventSource.onerror = () => {
        // EventSource will automatically reconnect
    };
}

function handlePipelineEvent(data) {
    const banner = document.getElementById('statusBanner');
    const title = document.getElementById('statusTitle');
    const desc = document.getElementById('statusDesc');
    const counter = document.getElementById('statusCounter');
    const icon = document.getElementById('statusIcon');

    if (data.status === 'idle') {
        banner.classList.add('hidden');
        return;
    }

    banner.classList.remove('hidden');
    title.textContent = data.message || 'Pipeline processing...';
    desc.textContent = data.details || '';
    counter.textContent = data.step ? `Step: ${data.step}` : 'Active';

    if (data.status === 'stopped') {
        if (icon) {
            icon.className = 'fa-solid fa-circle-xmark text-rose-400 text-xl';
        }
        setTimeout(() => {
            banner.classList.add('hidden');
            if (icon) {
                icon.className = 'fa-solid fa-circle-notch fa-spin text-indigo-400 text-xl';
            }
            loadCatalog();
        }, 3000);
        return;
    }

    if (data.status === 'completed') {
        setTimeout(() => {
            banner.classList.add('hidden');
            loadCatalog();
        }, 2000);
    }
}

async function stopAllProcessing() {
    const stopBtn = document.getElementById('stopAllBtn');
    const bannerStopBtn = document.getElementById('bannerStopBtn');
    const searchBtn = document.getElementById('searchBtn');

    if (stopBtn) {
        stopBtn.disabled = true;
        stopBtn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i><span>Stopping...</span>';
    }
    if (bannerStopBtn) {
        bannerStopBtn.disabled = true;
    }

    try {
        const response = await fetch('/api/stop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const result = await response.json();
        handlePipelineEvent({
            status: 'stopped',
            step: 'Stopped',
            message: 'All processing stopped.',
            details: result.message || 'Halted all downloads and video obfuscation.'
        });
    } catch (err) {
        alert('Failed to stop processing: ' + err.message);
    } finally {
        if (stopBtn) {
            stopBtn.disabled = false;
            stopBtn.innerHTML = '<i class="fa-solid fa-hand"></i><span>Stop</span>';
        }
        if (bannerStopBtn) {
            bannerStopBtn.disabled = false;
        }
        if (searchBtn) {
            searchBtn.disabled = false;
            searchBtn.innerHTML = '<i class="fa-solid fa-bolt"></i><span>Find</span>';
        }
    }
}

async function triggerSearch() {
    const query = document.getElementById('searchInput').value.trim();
    const limit = parseInt(document.getElementById('limitSelect').value, 10);
    const autoProcess = document.getElementById('autoProcessToggle').checked;
    const preset = document.getElementById('presetSelect').value;
    const mirror = document.getElementById('mirrorToggle').checked;

    if (!query) return;

    const btn = document.getElementById('searchBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i><span>Scraping...</span>';

    try {
        const response = await fetch('/api/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: query,
                limit: limit,
                auto_process: autoProcess,
                preset: preset,
                mirror: mirror
            })
        });

        const data = await response.json();
        if (data.videos) {
            discoveredVideos = data.videos;
            renderGrid();
        }
    } catch (err) {
        alert('Failed to execute search: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-bolt"></i><span>Find Shorts</span>';
    }
}

async function loadCatalog() {
    try {
        const response = await fetch('/api/videos');
        const data = await response.json();
        if (data.videos) {
            processedVideos = data.videos.filter(v => v.status === 'processed');
            if (currentTab === 'processed') {
                renderGrid();
            }
            updateBadges();
        }
    } catch (err) {
        // catalog sync error handled gracefully
    }
}

function updateBadges() {
    document.getElementById('resultsCountBadge').textContent = discoveredVideos.length;
    document.getElementById('processedCountBadge').textContent = processedVideos.length;
}

function switchTab(tab) {
    currentTab = tab;
    const tabResults = document.getElementById('tabResults');
    const tabProcessed = document.getElementById('tabProcessed');

    if (tab === 'results') {
        tabResults.className = 'font-semibold text-sm pb-2 border-b-2 border-indigo-500 text-white flex items-center space-x-2';
        tabProcessed.className = 'font-semibold text-sm pb-2 border-b-2 border-transparent text-slate-400 hover:text-slate-200 flex items-center space-x-2';
    } else {
        tabProcessed.className = 'font-semibold text-sm pb-2 border-b-2 border-indigo-500 text-white flex items-center space-x-2';
        tabResults.className = 'font-semibold text-sm pb-2 border-b-2 border-transparent text-slate-400 hover:text-slate-200 flex items-center space-x-2';
    }
    renderGrid();
}

function renderGrid() {
    const grid = document.getElementById('videoGrid');
    const empty = document.getElementById('emptyState');
    const list = currentTab === 'results' ? discoveredVideos : processedVideos;

    grid.innerHTML = '';
    updateBadges();

    if (!list || list.length === 0) {
        empty.classList.remove('hidden');
        grid.classList.add('hidden');
        return;
    }

    empty.classList.add('hidden');
    grid.classList.remove('hidden');

    list.forEach(video => {
        const card = createVideoCard(video);
        grid.appendChild(card);
    });
}

function createVideoCard(v) {
    const isProcessed = v.status === 'processed';
    const card = document.createElement('div');
    card.className = 'bg-slate-900 border border-slate-800/90 rounded-xl overflow-hidden shadow-lg hover:border-slate-700 transition flex flex-col justify-between group';

    const formattedViews = Number(v.views || 0).toLocaleString();
    const formattedLikes = Number(v.likes || 0).toLocaleString();

    card.innerHTML = `
        <div class="relative aspect-[9/16] bg-slate-950 overflow-hidden cursor-pointer" onclick="openPreview('${v.id}', '${isProcessed ? 'processed' : 'raw'}', '${encodeURIComponent(v.title || '')}')">
            <img src="${v.thumbnail_url || 'https://via.placeholder.com/360x640'}" 
                 class="w-full h-full object-cover group-hover:scale-105 transition duration-300"
                 alt="${v.title}">
            <div class="absolute inset-0 bg-gradient-to-t from-slate-950/90 via-transparent to-black/30"></div>
            
            <div class="absolute top-2 left-2 flex space-x-1.5">
                ${isProcessed 
                    ? '<span class="bg-emerald-600/90 backdrop-blur text-white text-[10px] font-bold px-2 py-0.5 rounded-md flex items-center space-x-1"><i class="fa-solid fa-shield-check"></i><span>OBFUSCATED</span></span>'
                    : '<span class="bg-indigo-600/90 backdrop-blur text-white text-[10px] font-bold px-2 py-0.5 rounded-md">ORIGINAL</span>'
                }
            </div>

            <div class="absolute top-2 right-2 bg-black/70 backdrop-blur text-slate-200 text-[10px] font-mono px-2 py-0.5 rounded">
                ${v.duration || '0'}s
            </div>

            <div class="absolute bottom-3 left-3 right-3 space-y-1">
                <p class="text-xs font-semibold text-white line-clamp-2 leading-snug">${v.title || 'Untitled'}</p>
                <p class="text-[11px] text-slate-400 truncate">${v.channel || 'Unknown Creator'}</p>
                
                <div class="flex items-center space-x-3 pt-1 text-[11px] text-slate-300">
                    <span class="flex items-center space-x-1"><i class="fa-solid fa-eye text-slate-400"></i><span>${formattedViews}</span></span>
                    <span class="flex items-center space-x-1"><i class="fa-solid fa-heart text-rose-400"></i><span>${formattedLikes}</span></span>
                </div>
            </div>
        </div>

        <div class="p-3 border-t border-slate-800 bg-slate-900/60 flex items-center justify-between gap-2">
            ${isProcessed
                ? `<a href="/api/download/${v.id}" download class="w-full bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium py-2 px-3 rounded-lg flex items-center justify-center space-x-1.5 shadow transition">
                     <i class="fa-solid fa-download"></i>
                     <span>Download MP4</span>
                   </a>`
                : `<button onclick="processSingleVideo('${v.id}')" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium py-2 px-3 rounded-lg flex items-center justify-center space-x-1.5 shadow transition">
                     <i class="fa-solid fa-wand-magic-sparkles"></i>
                     <span>Apply Noise & Download</span>
                   </button>`
            }
        </div>
    `;

    return card;
}

async function processSingleVideo(videoId) {
    const preset = document.getElementById('presetSelect').value;
    const mirror = document.getElementById('mirrorToggle').checked;

    try {
        const response = await fetch('/api/process', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                video_id: videoId,
                preset: preset,
                mirror: mirror
            })
        });
        const result = await response.json();
        if (result.success) {
            await loadCatalog();
            switchTab('processed');
        } else {
            alert('Processing error: ' + result.error);
        }
    } catch (err) {
        alert('Failed to process video: ' + err.message);
    }
}

function openPreview(videoId, type, titleEnc) {
    const modal = document.getElementById('videoModal');
    const player = document.getElementById('modalVideoPlayer');
    const title = document.getElementById('modalTitle');
    const downloadBtn = document.getElementById('modalDownloadBtn');
    const paramsDiv = document.getElementById('modalParams');

    title.textContent = decodeURIComponent(titleEnc) || 'Video Preview';
    player.src = `/api/stream/${type}/${videoId}`;
    downloadBtn.href = `/api/download/${videoId}`;

    // Look up video metadata
    const video = [...discoveredVideos, ...processedVideos].find(v => v.id === videoId);
    if (video && video.perturbation_params) {
        try {
            const p = JSON.parse(video.perturbation_params);
            paramsDiv.innerHTML = `
                <div class="grid grid-cols-2 gap-2">
                    <div><strong>Preset:</strong> ${p.preset}</div>
                    <div><strong>Playback Speed:</strong> ${p.speed}x</div>
                    <div><strong>Micro Zoom:</strong> ${p.zoom}x</div>
                    <div><strong>Noise Sigma:</strong> ${p.noise_sigma}</div>
                    <div><strong>Horizontal Mirror:</strong> ${p.mirror ? 'Enabled' : 'Disabled'}</div>
                    <div><strong>Container UUID:</strong> ${p.unique_id.slice(0, 8)}...</div>
                </div>
            `;
            paramsDiv.classList.remove('hidden');
        } catch (e) {
            paramsDiv.classList.add('hidden');
        }
    } else {
        paramsDiv.classList.add('hidden');
    }

    modal.classList.remove('hidden');
    player.play().catch(() => {});
}

function closeModal() {
    const modal = document.getElementById('videoModal');
    const player = document.getElementById('modalVideoPlayer');
    player.pause();
    player.src = '';
    modal.classList.add('hidden');
}

// Global initialization
window.addEventListener('DOMContentLoaded', () => {
    initEventSource();
    loadCatalog();
});
