/**
 * Reddit Story Shorts Generator - Frontend Application Logic
 */

let currentSelectedPost = null;
let activeEventSource = null;
let activeJobId = null;
let currentPosts = [];

document.addEventListener("DOMContentLoaded", () => {
    loadGameplayList();
    loadMusicList();
    loadGallery();
    fetchPosts(); // Load initial batch
});

function switchSourcingTab(tab) {
    const browseTab = document.getElementById("tab-browse");
    const urlTab = document.getElementById("tab-url");
    const browseBtn = document.getElementById("tab-browse-btn");
    const urlBtn = document.getElementById("tab-url-btn");

    if (tab === "browse") {
        browseTab.classList.remove("hidden");
        urlTab.classList.add("hidden");
        browseBtn.className = "px-4 py-1.5 rounded-md font-semibold bg-reddit text-white transition";
        urlBtn.className = "px-4 py-1.5 rounded-md font-medium text-gray-400 hover:text-white transition";
    } else {
        browseTab.classList.add("hidden");
        urlTab.classList.remove("hidden");
        urlBtn.className = "px-4 py-1.5 rounded-md font-semibold bg-reddit text-white transition";
        browseBtn.className = "px-4 py-1.5 rounded-md font-medium text-gray-400 hover:text-white transition";
    }
}

async function fetchPosts() {
    const sub = document.getElementById("sub-select").value;
    const sort = document.getElementById("sort-select").value;
    const limit = document.getElementById("limit-select").value;
    const container = document.getElementById("posts-container");
    const btn = document.getElementById("fetch-posts-btn");

    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner animate-spin"></i><span>Loading...</span>`;
    container.innerHTML = `<div class="col-span-full py-12 text-center text-gray-400 text-sm"><i class="fa-solid fa-spinner animate-spin text-reddit text-2xl mb-2 block"></i>Fetching stories from r/${sub}...</div>`;

    try {
        const res = await fetch(`/api/reddit/posts?subreddit=${encodeURIComponent(sub)}&sort=${sort}&limit=${limit}`);
        const data = await res.json();

        if (!data.success || !data.posts || data.posts.length === 0) {
            container.innerHTML = `<div class="col-span-full py-8 text-center text-gray-500">No stories found in r/${sub}. Try another subreddit or sort.</div>`;
            return;
        }

        container.innerHTML = "";
        currentPosts = data.posts || [];
        currentPosts.forEach((post, index) => {
            const card = document.createElement("div");
            card.className = "p-4 rounded-xl bg-darkBg border border-darkBorder hover:border-reddit/60 transition flex flex-col justify-between space-y-3";
            card.innerHTML = `
                <div class="space-y-2">
                    <div class="flex items-center justify-between text-[11px] text-gray-400">
                        <div class="flex items-center space-x-2">
                            <span class="font-bold text-reddit">${post.subreddit}</span>
                            ${post.source === "curated_viral" ? '<span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">🔥 Viral Classic</span>' : '<span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">⚡ Live</span>'}
                        </div>
                        <span>u/${post.author}</span>
                    </div>
                    <h4 class="text-sm font-bold text-gray-100 line-clamp-2">${post.title}</h4>
                    <p class="text-xs text-gray-400 line-clamp-3">${post.body || "(Empty body text)"}</p>
                </div>
                <div class="pt-2 border-t border-darkBorder/50 flex items-center justify-between text-xs">
                    <div class="flex items-center space-x-2 text-gray-400">
                        <span>▲ ${(post.score >= 1000 ? (post.score/1000).toFixed(1)+'k' : post.score)}</span>
                        <span>⏱ ~${post.est_duration_seconds}s</span>
                    </div>
                    <button class="px-3 py-1 bg-reddit/20 hover:bg-reddit text-reddit hover:text-white font-bold rounded-lg transition" onclick="selectStoryByIndex(${index})">
                        Select
                    </button>
                </div>
            `;
            container.appendChild(card);
        });
    } catch (err) {
        container.innerHTML = `<div class="col-span-full py-8 text-center text-red-400">Failed to fetch stories: ${err.message}</div>`;
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-magnifying-glass"></i><span>Fetch Stories</span>`;
    }
}

async function fetchPostByUrl() {
    const url = document.getElementById("direct-url-input").value.trim();
    const btn = document.getElementById("fetch-url-btn");
    if (!url) return;

    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner animate-spin"></i>`;

    try {
        const res = await fetch("/api/reddit/post-by-url", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url }),
        });
        const data = await res.json();
        if (data.success && data.post) {
            selectStory(data.post);
            if (data.post.needs_body || !data.post.body) {
                const bodyEl = document.getElementById("editor-body");
                if (bodyEl) {
                    bodyEl.placeholder = "Title extracted from URL! Paste the story narrative body text here...";
                    bodyEl.focus();
                    bodyEl.scrollIntoView({ behavior: "smooth", block: "center" });
                }
            }
        } else {
            alert(
                "Reddit's anti-bot policy blocked direct automated access to this URL.\n\n" +
                "Quick Fix: Since you have the story open in your browser, simply copy the title and story text directly into the Script Editor below!"
            );
            const titleEl = document.getElementById("editor-title");
            if (titleEl) {
                titleEl.focus();
                titleEl.scrollIntoView({ behavior: "smooth", block: "center" });
            }
        }
    } catch (err) {
        alert("Network error: " + err.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-arrow-down-to-bracket"></i><span>Load Post</span>`;
    }
}

function selectStory(post) {
    if (!post) return;
    currentSelectedPost = post;
    const titleEl = document.getElementById("editor-title");
    const bodyEl = document.getElementById("editor-body");
    if (titleEl) titleEl.value = post.title || "";
    if (bodyEl) bodyEl.value = post.body || post.selftext || post.raw_body || "";
    updateScriptStats();

    // Smooth scroll down to editor
    if (titleEl) titleEl.scrollIntoView({ behavior: "smooth", block: "center" });

    if (document.getElementById("split-parts-toggle").checked) {
        previewParts();
    }
}

function selectStoryByIndex(index) {
    if (currentPosts && currentPosts[index]) {
        selectStory(currentPosts[index]);
    }
}

function updateScriptStats() {
    const title = document.getElementById("editor-title").value;
    const body = document.getElementById("editor-body").value;
    const combined = `${title} ${body}`.trim();
    const words = combined ? combined.split(/\s+/).length : 0;
    const estSec = Math.round((words / 150) * 60);

    document.getElementById("word-count-badge").innerText = `${words} words`;
    document.getElementById("est-duration-badge").innerText = `⏱ ~${estSec}s`;

    if (words > 175) {
        document.getElementById("split-parts-toggle").checked = true;
        toggleSplitOptions();
    }
}

function toggleSplitOptions() {
    const isChecked = document.getElementById("split-parts-toggle").checked;
    const controls = document.getElementById("split-controls");
    const container = document.getElementById("parts-preview-container");

    if (isChecked) {
        controls.classList.remove("hidden");
        container.classList.remove("hidden");
        previewParts();
    } else {
        controls.classList.add("hidden");
        container.classList.add("hidden");
    }
}

async function previewParts() {
    const title = document.getElementById("editor-title").value;
    const body = document.getElementById("editor-body").value;
    const maxSec = parseInt(document.getElementById("max-duration-select").value);
    const container = document.getElementById("parts-preview-container");

    if (!body.trim()) {
        container.innerHTML = "";
        return;
    }

    try {
        const res = await fetch("/api/split-story", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title, body, max_duration_seconds: maxSec }),
        });
        const data = await res.json();
        if (data.parts) {
            container.innerHTML = `
                <div class="text-xs font-semibold text-gray-400 mb-2">Split Plan (${data.parts.length} sequential parts):</div>
                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    ${data.parts.map(p => `
                        <div class="p-3 bg-darkBorder/40 rounded-lg text-xs space-y-1">
                            <div class="flex justify-between font-bold text-gray-200">
                                <span>Part ${p.part} / ${p.total_parts}</span>
                                <span class="text-neonYellow">⏱ ~${p.est_duration_seconds}s</span>
                            </div>
                            <p class="text-gray-400 text-[11px] line-clamp-3">${p.script}</p>
                        </div>
                    `).join("")}
                </div>
            `;
        }
    } catch (err) {
        console.error("Preview split failed:", err);
    }
}

async function previewVoice() {
    const voice = document.getElementById("voice-select").value;
    const rate = document.getElementById("voice-rate-select").value;
    const title = document.getElementById("editor-title").value;
    const body = document.getElementById("editor-body").value;
    const sampleText = `${title}. ${body}`.slice(0, 150) || "Testing this voice narration for Reddit stories.";
    const btn = document.getElementById("preview-voice-btn");
    const audio = document.getElementById("voice-preview-audio");

    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner animate-spin"></i><span>...</span>`;

    try {
        const res = await fetch("/api/tts/preview", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: sampleText, voice, rate }),
        });
        const data = await res.json();
        if (data.success && data.preview_url) {
            audio.src = data.preview_url;
            audio.classList.remove("hidden");
            audio.play();
        } else {
            alert("TTS Preview failed: " + (data.error || "Unknown error"));
        }
    } catch (err) {
        alert("Error testing voice: " + err.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-play"></i><span>Test</span>`;
    }
}

function updateVolLabels() {
    document.getElementById("voice-vol-label").innerText = `${document.getElementById("voice-vol-slider").value}%`;
    document.getElementById("bgm-vol-label").innerText = `${document.getElementById("bgm-vol-slider").value}%`;
}

async function loadGameplayList() {
    try {
        const res = await fetch("/api/gameplay/list");
        const data = await res.json();
        const select = document.getElementById("gameplay-select");
        select.innerHTML = "";

        if (data.videos && data.videos.length > 0) {
            data.videos.forEach(v => {
                const opt = document.createElement("option");
                opt.value = v.filename;
                opt.innerText = `${v.filename} (${Math.round(v.duration)}s, ${v.width}x${v.height})`;
                select.appendChild(opt);
            });
        } else {
            const opt = document.createElement("option");
            opt.value = "";
            opt.innerText = "Default Procedural Gameplay (1080x1920)";
            select.appendChild(opt);
        }
    } catch (err) {
        console.error("Failed to load gameplay list:", err);
    }
}

async function loadMusicList() {
    try {
        const res = await fetch("/api/music/list");
        const data = await res.json();
        const select = document.getElementById("bgm-select");
        select.innerHTML = `<option value="">No Background Music</option>`;
        if (data.tracks) {
            data.tracks.forEach(t => {
                const opt = document.createElement("option");
                opt.value = t.id;
                opt.innerText = t.name;
                select.appendChild(opt);
            });
        }
    } catch (err) {
        console.error("Failed to load music list:", err);
    }
}

async function startRender() {
    const title = document.getElementById("editor-title").value.trim();
    const body = document.getElementById("editor-body").value.trim();

    if (!title) {
        alert("Please enter or select a story title first.");
        return;
    }

    const banner = document.getElementById("render-banner");
    const titleEl = document.getElementById("render-status-title");
    const descEl = document.getElementById("render-status-desc");
    const pctEl = document.getElementById("render-percentage");
    const barEl = document.getElementById("render-progress-bar");
    const completedLinks = document.getElementById("render-completed-links");
    const renderBtn = document.getElementById("start-render-btn");

    banner.classList.remove("hidden");
    completedLinks.classList.add("hidden");
    completedLinks.innerHTML = "";
    banner.scrollIntoView({ behavior: "smooth" });

    renderBtn.disabled = true;
    renderBtn.classList.add("opacity-50", "cursor-not-allowed");

    const payload = {
        title,
        body,
        subreddit: currentSelectedPost ? currentSelectedPost.subreddit : "r/AmItheAsshole",
        author: currentSelectedPost ? currentSelectedPost.author : "StoryTeller",
        score: currentSelectedPost ? currentSelectedPost.score : 18500,
        num_comments: currentSelectedPost ? currentSelectedPost.num_comments : 1240,
        voice: document.getElementById("voice-select").value,
        voice_rate: document.getElementById("voice-rate-select").value,
        gameplay_filename: document.getElementById("gameplay-select").value || null,
        bgm_filename: document.getElementById("bgm-select").value || null,
        voice_volume: parseInt(document.getElementById("voice-vol-slider").value) / 100.0,
        gameplay_volume: 0.10,
        bgm_volume: parseInt(document.getElementById("bgm-vol-slider").value) / 100.0,
        show_title_card: document.getElementById("title-card-toggle").checked,
        split_parts: document.getElementById("split-parts-toggle").checked,
        max_part_duration: parseInt(document.getElementById("max-duration-select").value),
    };

    try {
        const res = await fetch("/api/render", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!data.success || !data.job_id) {
            throw new Error(data.error || "Failed to start render");
        }

        const jobId = data.job_id;
        activeJobId = jobId;

        const cancelBtn = document.getElementById("cancel-render-btn");
        if (cancelBtn) {
            cancelBtn.classList.remove("hidden");
            cancelBtn.disabled = false;
            cancelBtn.innerHTML = `<i class="fa-solid fa-stop"></i><span>Stop Rendering</span>`;
        }

        if (activeEventSource) activeEventSource.close();

        activeEventSource = new EventSource(`/api/render/stream/${jobId}`);
        activeEventSource.addEventListener("update", (e) => {
            const status = JSON.parse(e.data);
            const progress = status.progress || 0;
            barEl.style.width = `${progress}%`;
            pctEl.innerText = `${Math.round(progress)}%`;
            descEl.innerText = status.step || "Processing...";

            if (status.status === "completed") {
                activeEventSource.close();
                titleEl.innerText = "🎉 Video Generation Complete!";
                descEl.innerText = "All parts rendered into 9:16 vertical MP4 format.";
                renderBtn.disabled = false;
                renderBtn.classList.remove("opacity-50", "cursor-not-allowed");
                if (cancelBtn) cancelBtn.classList.add("hidden");

                if (status.videos && status.videos.length > 0) {
                    completedLinks.classList.remove("hidden");
                    completedLinks.innerHTML = status.videos.map(v => `
                        <a href="${v.video_url}" target="_blank" download class="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs flex items-center space-x-2">
                            <i class="fa-solid fa-download"></i>
                            <span>Download Part ${v.part} (${v.duration}s)</span>
                        </a>
                    `).join("");
                }
                loadGallery();
            } else if (status.status === "cancelled") {
                activeEventSource.close();
                titleEl.innerText = "⏹ Render Stopped";
                descEl.innerText = "The video rendering process was stopped by user.";
                barEl.style.width = "0%";
                pctEl.innerText = "0%";
                renderBtn.disabled = false;
                renderBtn.classList.remove("opacity-50", "cursor-not-allowed");
                if (cancelBtn) cancelBtn.classList.add("hidden");
            } else if (status.status === "failed") {
                activeEventSource.close();
                titleEl.innerText = "❌ Render Failed";
                descEl.innerText = status.error || "Unknown rendering error.";
                renderBtn.disabled = false;
                renderBtn.classList.remove("opacity-50", "cursor-not-allowed");
                if (cancelBtn) cancelBtn.classList.add("hidden");
            }
        });

    } catch (err) {
        titleEl.innerText = "❌ Error Starting Render";
        descEl.innerText = err.message;
        renderBtn.disabled = false;
        renderBtn.classList.remove("opacity-50", "cursor-not-allowed");
        const cancelBtn = document.getElementById("cancel-render-btn");
        if (cancelBtn) cancelBtn.classList.add("hidden");
    }
}

async function cancelRender() {
    if (!activeJobId) return;
    const cancelBtn = document.getElementById("cancel-render-btn");
    const descEl = document.getElementById("render-status-desc");
    if (cancelBtn) {
        cancelBtn.disabled = true;
        cancelBtn.innerHTML = `<i class="fa-solid fa-spinner animate-spin"></i><span>Stopping...</span>`;
    }
    if (descEl) descEl.innerText = "Stopping video generation...";
    try {
        await fetch(`/api/render/cancel/${activeJobId}`, { method: "POST" });
    } catch (err) {
        console.error("Cancel failed:", err);
    }
}

async function loadGallery() {
    const container = document.getElementById("gallery-container");
    try {
        const res = await fetch("/api/videos");
        const data = await res.json();
        if (!data.videos || data.videos.length === 0) {
            container.innerHTML = `<div class="col-span-full py-8 text-center text-gray-500 text-sm">No rendered videos yet. Click "Render Video Now" above to generate your first short!</div>`;
            return;
        }

        container.innerHTML = "";
        data.videos.forEach(v => {
            const card = document.createElement("div");
            card.className = "rounded-xl overflow-hidden bg-darkBg border border-darkBorder flex flex-col justify-between";
            card.innerHTML = `
                <div class="relative aspect-[9/16] bg-black">
                    <video src="${v.video_url}" controls preload="metadata" class="w-full h-full object-cover"></video>
                </div>
                <div class="p-3 space-y-2">
                    <div class="text-xs font-bold truncate text-gray-200" title="${v.filename}">${v.filename}</div>
                    <div class="flex items-center justify-between text-[11px] text-gray-400">
                        <span>${v.size_mb} MB</span>
                        <div class="flex items-center space-x-2">
                            <a href="${v.video_url}" download class="text-emerald-400 hover:text-emerald-300" title="Download Video">
                                <i class="fa-solid fa-download"></i>
                            </a>
                            <button onclick="deleteVideo('${v.filename}')" class="text-red-400 hover:text-red-300" title="Delete Video">
                                <i class="fa-solid fa-trash"></i>
                            </button>
                        </div>
                    </div>
                </div>
            `;
            container.appendChild(card);
        });
    } catch (err) {
        console.error("Failed to load gallery:", err);
    }
}

async function deleteVideo(filename) {
    if (!confirm(`Delete ${filename}?`)) return;
    try {
        await fetch(`/api/videos/${encodeURIComponent(filename)}`, { method: "DELETE" });
        loadGallery();
    } catch (err) {
        alert("Failed to delete video: " + err.message);
    }
}

function openDownloadModal() {
    document.getElementById("download-modal").classList.remove("hidden");
}

function closeDownloadModal() {
    document.getElementById("download-modal").classList.add("hidden");
}

function selectPresetUrl(url, id) {
    document.getElementById("custom-yt-url").value = url;
}

async function triggerGameplayDownload() {
    const url = document.getElementById("custom-yt-url").value.trim();
    if (!url) {
        alert("Please enter or select a YouTube URL.");
        return;
    }
    const formData = new FormData();
    formData.append("url", url);

    try {
        const res = await fetch("/api/gameplay/download", { method: "POST", body: formData });
        const data = await res.json();
        alert(data.message || "Download started in background.");
        closeDownloadModal();
    } catch (err) {
        alert("Download trigger failed: " + err.message);
    }
}
