const form = document.querySelector('#form');
const status = document.querySelector('#status');
const progress = document.querySelector('#progress');
const download = document.querySelector('#download');
const exportButton = document.querySelector('#export');
let exporting = false;
let countryRoster = {};
let audioContext;
let audioEvents;
let soundEnabled = false;
const effectBuffers = new Map();
const playingSounds = new Set();
const soundButton = document.querySelector('#sound');
function stopPreviewAudio() {
  audioEvents?.close();
  audioEvents = undefined;
  for (const source of playingSounds) { try { source.stop(); } catch (_) {} }
  playingSounds.clear();
}
function startPreviewAudio(value) {
  stopPreviewAudio();
  if (!soundEnabled) return;
  audioEvents = new EventSource('/api/preview-events?settings=' + encodeURIComponent(JSON.stringify(value)));
  audioEvents.onmessage = message => {
    for (const event of JSON.parse(message.data)) {
      const buffer = effectBuffers.get(event.kind);
      if (!buffer) continue;
      const source = audioContext.createBufferSource();
      const gain = audioContext.createGain();
      source.buffer = buffer;
      gain.gain.value = event.gain * .65;
      source.connect(gain).connect(audioContext.destination);
      source.onended = () => playingSounds.delete(source);
      playingSounds.add(source);
      source.start();
    }
  };
  audioEvents.addEventListener('done', () => { audioEvents?.close(); audioEvents = undefined; });
  audioEvents.onerror = () => { audioEvents?.close(); audioEvents = undefined; };
}
soundButton.onclick = async () => {
  try {
    if (soundEnabled) {
      soundEnabled = false;
      stopPreviewAudio();
    } else {
      soundButton.disabled = true;
      audioContext ??= new AudioContext();
      await audioContext.resume();
      const names = ['whoosh', 'hit', 'shield', 'shatter', 'heal', 'rage', 'twin', 'overdrive', 'knockout', 'victory', 'draw', 'heartbeat'];
      await Promise.all(names.map(async name => {
        if (effectBuffers.has(name)) return;
        const response = await fetch('/api/sounds/' + name);
        if (!response.ok) throw new Error('Could not load sound effects.');
        effectBuffers.set(name, await audioContext.decodeAudioData(await response.arrayBuffer()));
      }));
      soundEnabled = true;
      preview();
    }
  } catch (error) { soundEnabled = false; status.textContent = error.message; }
  finally {
    soundButton.disabled = false;
    soundButton.textContent = soundEnabled ? 'Mute preview' : 'Enable sound';
    soundButton.setAttribute('aria-pressed', String(soundEnabled));
  }
};
window.addEventListener('pagehide', stopPreviewAudio);
function countryCode(input) {
  const value = input.value.trim().toLowerCase();
  const match = Object.entries(countryRoster).find(([code, name]) =>
    code.toLowerCase() === value || name.toLowerCase() === value || `${name} (${code})`.toLowerCase() === value);
  if (!match) throw new Error('Choose a country from the search suggestions, or enter its two-letter code.');
  return match[0];
}
function updateFlags() {
  for (let index = 1; index <= 2; index++) {
    try {
      const code = countryCode(document.querySelector('#fighter' + index));
      const image = document.querySelector('#flag' + index);
      image.src = `/flags/${code}.png`;
      image.alt = `${countryRoster[code]} flag`;
    } catch (_) { /* Allow partial search input while typing. */ }
  }
}
function settings() {
  if (!form.reportValidity()) throw new Error('Check the settings above.');
  const value = Object.fromEntries([...new FormData(form)].map(([key, value]) => [key, Number(value)]));
  value.countries = [1, 2].map(index => countryCode(document.querySelector('#fighter' + index)));
  if (value.countries[0] === value.countries[1]) throw new Error('Choose two different countries for the 1v1 battle.');
  return value;
}
function preview(value = settings()) {
  document.querySelector('#preview').src = '/api/preview?settings=' + encodeURIComponent(JSON.stringify(value)) + '&replay=' + Date.now();
  startPreviewAudio(value);
  if (!exporting) status.textContent = 'Battle running. Replay any time.';
}
async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Invalid battle settings.');
  return data;
}
document.querySelector('#preview-button').onclick = () => {
  try { preview(); } catch (error) { status.textContent = error.message; }
};
document.querySelector('#shuffle').onclick = () => {
  form.elements.seed.value = crypto.getRandomValues(new Uint32Array(1))[0] % 2147483647;
  try { preview(); } catch (error) { status.textContent = error.message; }
};
form.onsubmit = async event => {
  event.preventDefault();
  if (exporting) return;
  try {
    const value = settings();
    exporting = true;
    exportButton.disabled = true;
    download.hidden = true;
    progress.hidden = false;
    progress.value = 0;
    status.textContent = 'Starting MP4 export…';
    preview(value);
    const job = await request('/api/export', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(value)});
    for (;;) {
      const result = await request('/api/jobs/' + job.id);
      progress.value = result.progress;
      status.textContent = `Rendering video… ${result.progress}%`;
      if (result.status === 'failed') throw new Error(result.error);
      if (result.status === 'complete') {
        status.textContent = 'Your battle is ready. Download the MP4 below.';
        download.href = result.download;
        download.hidden = false;
        break;
      }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
  } catch (error) { status.textContent = error.message; }
  finally { exporting = false; exportButton.disabled = false; progress.hidden = true; }
};
(async () => {
  try {
    const countries = await request('/api/countries');
    countryRoster = countries;
    for (const [code, name] of Object.entries(countries)) {
      const option = document.createElement('option');
      option.value = `${name} (${code})`;
      document.querySelector('#country-list').append(option);
    }
    document.querySelector('#roster').textContent = `${Object.keys(countries).length} countries and territories · search by name or code`;
    for (const input of document.querySelectorAll('.fighter input')) input.addEventListener('input', updateFlags);
    document.querySelector('#random-match').onclick = () => {
      const codes = Object.keys(countryRoster);
      const first = crypto.getRandomValues(new Uint32Array(1))[0] % codes.length;
      const remaining = codes.filter((_, index) => index !== first);
      const second = remaining[crypto.getRandomValues(new Uint32Array(1))[0] % remaining.length];
      document.querySelector('#fighter1').value = `${countries[codes[first]]} (${codes[first]})`;
      document.querySelector('#fighter2').value = `${countries[second]} (${second})`;
      updateFlags();
      preview();
    };
    updateFlags();
    preview();
  } catch (error) { status.textContent = error.message; }
})();
