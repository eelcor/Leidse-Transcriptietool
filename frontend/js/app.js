import { API } from './api.js';
import { Recorder, listMics, loadSettings } from './recorder.js';
import { renderMarkdown } from './md.js';

let CONFIG = { max_upload_mb: 200, retention_workdays: 2, default_language: 'nl', word_timestamps: true };
let SECTIONS = [];
let recorder = null;
let sse = null;

const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kid of kids) n.append(kid?.nodeType ? kid : document.createTextNode(kid ?? ''));
  return n;
};

// Gestylde line-SVG-iconen (currentColor) i.p.v. emoji.
const ICONS = {
  key: '<circle cx="6" cy="12" r="4"/><path d="M10 12h11"/><path d="M16 12v3.5M19 12v3.5"/>',
  download: '<path d="M12 3v12M8 11l4 4 4-4"/><path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/>',
  trash: '<path d="M4 7h16M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2M6 7l1 13a1 1 0 001 1h8a1 1 0 001-1l1-13"/>',
  transcript: '<path d="M4 6h16M4 12h16M4 18h10"/>',
  report: '<path d="M6 3h8l5 5v12a1 1 0 01-1 1H6a1 1 0 01-1-1V4a1 1 0 011-1z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
  sparkle: '<path d="M12 3l1.7 4.8L18.5 9.5l-4.8 1.7L12 16l-1.7-4.8L5.5 9.5l4.8-1.7z"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  word: '<path d="M6 3h8l5 5v12a1 1 0 01-1 1H6a1 1 0 01-1-1V4a1 1 0 011-1z"/><path d="M14 3v5h5"/><path d="M8.3 12l1.2 4.5L11 12l1.5 4.5L13.7 12"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 012-2h10"/>',
  markdown: '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 15V9l3 3 3-3v6"/><path d="M17 9v4M15 12l2 2 2-2"/>',
};
function ic(name, size = 15) {
  const w = document.createElement('span');
  w.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:${size}px;height:${size}px;vertical-align:-2px;flex:none" aria-hidden="true">${ICONS[name] || ''}</svg>`;
  return w.firstChild;
}

// Leesbare bestandsnaam voor de lokale opname: opname-2026-07-27_14-32-05.webm
function opnameFilename() {
  const d = new Date(), p = (n) => String(n).padStart(2, '0');
  return `opname-${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_${p(d.getHours())}-${p(d.getMinutes())}-${p(d.getSeconds())}.webm`;
}

function show(view) {
  document.querySelectorAll('.view').forEach((v) => (v.hidden = true));
  $('#view-' + view).hidden = false;
  const stepFor = { home: 1, status: 2, retrieve: 0 };
  if (view in stepFor) setStep(stepFor[view]);
}

// Voortgangs-stepper: 1 Kiezen · 2 Verwerken · 3 Transcript & verslag.
function setStep(n) {
  const st = document.getElementById('stepper');
  if (!st) return;
  st.hidden = !n;
  st.querySelectorAll('li[data-step]').forEach((li) => {
    const i = +li.getAttribute('data-step');
    li.dataset.state = n && i < n ? 'done' : (i === n ? 'active' : '');
  });
}

function fmtDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('nl-NL', { dateStyle: 'full', timeStyle: 'short' });
  } catch { return iso; }
}

const STATUS_LABEL = {
  created: 'Aangemaakt', queued: 'In de wachtrij', transcribing: 'Bezig met transcriberen…',
  transcribed: 'Transcript klaar', failed: 'Mislukt',
};

// -------------------------------------------------------------------------
// Init
// -------------------------------------------------------------------------
async function init() {
  try { CONFIG = await API.config(); } catch {}
  try { SECTIONS = (await API.prompts()).sections; } catch {}
  $('#max-size').textContent = CONFIG.max_upload_mb;
  $('#retention').textContent = CONFIG.retention_workdays;
  const optDefault = CONFIG.audio_optimize_default !== false;
  $('#opt-upload').checked = optDefault;
  $('#opt-record').checked = optDefault;
  // Indicatie hoe lang je bij de max-grootte kunt opnemen (op basis van 48 kbps opname).
  const recBitrate = (loadSettings().bitrate || 48000);
  const hours = (CONFIG.max_upload_mb * 1024 * 1024 * 8) / recBitrate / 3600;
  $('#max-dur').textContent = `(± ${Math.round(hours)} uur opname)`;

  // Werkelijke modelnamen uit de env (via /api/config) in de voettekst.
  const fm = $('#foot-models');
  if (fm && (CONFIG.stt_label || CONFIG.llm_model)) {
    const parts = [];
    if (CONFIG.stt_label) parts.push(`STT: ${CONFIG.stt_label}`);
    if (CONFIG.llm_model) parts.push(`Verslag: ${CONFIG.llm_model}`);
    parts.push(`auto-verwijderen na ${CONFIG.retention_workdays} werkdagen`);
    fm.textContent = parts.join(' · ');
    fm.hidden = false;
  }

  // Toon het "certificaat installeren"-linkje alleen als er een interne CA beschikbaar is
  // (dus bij een self-signed opzet; op prod met een echt certificaat blijft het verborgen).
  fetch('/caddy-root.crt', { method: 'HEAD' })
    .then((r) => { if (r.ok) { const n = $('#cert-note'); if (n) n.hidden = false; } })
    .catch(() => {});

  // Navigatie
  $('#nav-new').addEventListener('click', () => show('home'));
  $('#nav-retrieve').addEventListener('click', () => show('retrieve'));

  setupReportConfig();
  setupUpload();
  setupRecorder();
  setupRetrieve();
  setupAutohideTopbar();

  // Diep-link: #s=<sessionId>
  const m = location.hash.match(/s=([^&]+)/);
  if (m) { openSession(decodeURIComponent(m[1])); } else { show('home'); }
}

// -------------------------------------------------------------------------
// Verslag-opties op het startscherm (auto-verslag na transcriptie)
// -------------------------------------------------------------------------
const repBoxes = {};
function setupReportConfig() {
  const chips = $('#rep-chips');
  SECTIONS.filter((s) => s.key !== 'volledig').forEach((s) => {
    const cb = el('input', { type: 'checkbox' });
    repBoxes[s.key] = cb;
    const chip = el('label', { class: 'chip' }, cb, s.label);
    cb.addEventListener('change', () => chip.classList.toggle('on', cb.checked));
    chips.append(chip);
  });
  document.querySelectorAll('input[name="rep-mode"]').forEach((r) => {
    r.addEventListener('change', () => {
      $('#rep-custom').hidden = document.querySelector('input[name="rep-mode"]:checked').value !== 'custom';
    });
  });
}

// Lees de gekozen verslag-config; geeft {kinds,custom_prompt,context} of null.
function getReportConfig() {
  const mode = (document.querySelector('input[name="rep-mode"]:checked') || {}).value || 'none';
  if (mode === 'none') return null;
  if (mode === 'full') return { kinds: ['volledig'] };
  const kinds = Object.entries(repBoxes).filter(([, cb]) => cb.checked).map(([k]) => k);
  const custom_prompt = ($('#rep-prompt').value || '').trim() || null;
  const context = ($('#rep-context').value || '').trim() || null;
  if (!kinds.length && !custom_prompt) return null;
  return { kinds: kinds.length ? kinds : null, custom_prompt, context };
}

// -------------------------------------------------------------------------
// Bestand uploaden
// -------------------------------------------------------------------------
function setupUpload() {
  const input = $('#file-input');
  const btn = $('#upload-btn');
  const prog = $('#upload-progress');

  // Sleep-en-neerzet op de upload-kaart: gedropte audio in de file-input zetten.
  const card = $('#upload-card');
  const hint = $('#dz-hint');
  if (card) {
    const over = (on) => { card.classList.toggle('drag', on); if (hint) hint.hidden = !on; };
    ['dragenter', 'dragover'].forEach((ev) => card.addEventListener(ev, (e) => { e.preventDefault(); over(true); }));
    ['dragleave', 'dragend'].forEach((ev) => card.addEventListener(ev, (e) => { e.preventDefault(); over(false); }));
    card.addEventListener('drop', (e) => {
      e.preventDefault(); over(false);
      const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (!f) return;
      try { const dt = new DataTransfer(); dt.items.add(f); input.files = dt.files; }
      catch { /* oudere browser: file-input laat 'm dan zelf niet zetten */ }
    });
  }

  btn.addEventListener('click', async () => {
    const file = input.files[0];
    if (!file) { alert('Kies eerst een bestand.'); return; }
    const maxBytes = CONFIG.max_upload_mb * 1024 * 1024;
    if (file.size > maxBytes) { alert(`Bestand te groot (max ${CONFIG.max_upload_mb} MB).`); return; }
    const optimize = $('#opt-upload').checked;
    btn.disabled = true;
    prog.hidden = false;
    try {
      const res = await API.uploadFileChunked(file, CONFIG.default_language, optimize, getReportConfig(), (f) => {
        prog.value = Math.round(f * 100);
      });
      openSession(res.id);
    } catch (e) {
      alert('Upload mislukt: ' + e.message);
    } finally {
      btn.disabled = false;
    }
  });
}

// -------------------------------------------------------------------------
// Opnemen
// -------------------------------------------------------------------------
function setupRecorder() {
  const s = loadSettings();
  const startBtn = $('#rec-start');
  const stopBtn = $('#rec-stop');
  const pauseBtn = $('#rec-pause');
  const meter = $('#vu-fill');
  const meterWrap = $('#vu');
  const timeEl = $('#rec-time');
  const dl = $('#rec-download');

  // Toggles koppelen aan settings
  const bind = (id, key) => {
    const cb = $('#' + id);
    cb.checked = !!s[key];
    cb.addEventListener('change', async () => {
      if (recorder) await recorder.applyConstraints({ [key]: cb.checked });
      else { const st = loadSettings(); st[key] = cb.checked; localStorage.setItem('transcribe.recorder.settings.v1', JSON.stringify(st)); }
      if (key === 'autoGainControl') updateGainHint();
    });
  };
  bind('tg-agc', 'autoGainControl');
  bind('tg-echo', 'echoCancellation');
  bind('tg-noise', 'noiseSuppression');
  bind('tg-hp', 'highpass');
  bind('tg-vad', 'vadTrim');

  const gain = $('#sensitivity');
  gain.value = s.gain;
  const updateGainHint = () => {
    const agc = $('#tg-agc').checked;
    $('#sensitivity-wrap').classList.toggle('dimmed', agc);
    $('#gain-hint').textContent = agc
      ? 'AGC staat aan — de browser regelt het niveau; deze schuif is fijnafstemming.'
      : 'Praat even en zet de schuif zo dat de balk in het groen piekt.';
  };
  gain.addEventListener('input', () => { if (recorder) recorder.setGain(parseFloat(gain.value)); });
  updateGainHint();

  // Opnamekwaliteit (bitrate)
  const quality = $('#rec-quality');
  if (s.bitrate) quality.value = String(s.bitrate);
  quality.addEventListener('change', () => {
    const v = parseInt(quality.value, 10);
    if (recorder) recorder.setBitrate(v);
    else { const st = loadSettings(); st.bitrate = v; localStorage.setItem('transcribe.recorder.settings.v1', JSON.stringify(st)); }
  });

  // Audio lokaal opslaan (standaard uit)
  const saveLocal = $('#opt-savelocal');
  saveLocal.checked = !!s.saveLocal;
  saveLocal.addEventListener('change', () => {
    const st = loadSettings(); st.saveLocal = saveLocal.checked;
    localStorage.setItem('transcribe.recorder.settings.v1', JSON.stringify(st));
  });

  // Opnamebron: microfoon / vergaderingsgeluid (tab of scherm, bijv. Teams) / beide.
  const sourceSel = $('#rec-source');
  const sourceHint = $('#rec-source-hint');
  const enableBtn = $('#rec-enable');
  const SRC_HINT = {
    mic: 'Neemt je microfoon op (je eigen stem).',
    system: 'Kies straks het Teams-venster of -tabblad en deel het mét geluid. Systeemgeluid delen werkt het best in Chrome/Edge op Windows; op macOS werkt alleen tabblad-geluid.',
    both: 'Neemt je microfoon én het gedeelde vergaderingsgeluid op — handig als je zelf ook meepraat.',
  };
  const SRC_LABEL = { mic: 'Microfoon inschakelen', system: 'Vergaderingsgeluid delen', both: 'Microfoon + geluid delen' };
  const applySourceUI = () => {
    const v = sourceSel.value;
    if (sourceHint) sourceHint.textContent = SRC_HINT[v] || '';
    if (enableBtn && !enableBtn.hidden) enableBtn.textContent = SRC_LABEL[v] || 'Inschakelen';
  };
  if (sourceSel) {
    sourceSel.value = s.source || 'mic';
    applySourceUI();
    sourceSel.addEventListener('change', async () => {
      const st = loadSettings(); st.source = sourceSel.value;
      localStorage.setItem('transcribe.recorder.settings.v1', JSON.stringify(st));
      applySourceUI();
      if (recorder) {
        try { await recorder.applyConstraints({ source: sourceSel.value }); }
        catch (e) { alert('Kon de opnamebron niet wijzigen: ' + e.message); }
      }
    });
  }

  let startTs = 0, timer = null, uploadChain = Promise.resolve(), sessionId = null, chunkErr = false;

  async function refreshMics() {
    try {
      const mics = await listMics();
      const sel = $('#mic-select');
      sel.innerHTML = '';
      mics.forEach((m, i) => sel.append(el('option', { value: m.deviceId }, m.label || `Microfoon ${i + 1}`)));
      if (s.deviceId) sel.value = s.deviceId;
      sel.onchange = async () => { if (recorder) await recorder.applyConstraints({ deviceId: sel.value }); };
    } catch {}
  }

  $('#rec-enable').addEventListener('click', async () => {
    try {
      recorder = new Recorder();
      const vuPeak = $('#vu-peak'), vuZone = $('#vu-zone'), vuPeakDb = $('#vu-peak-db');
      const dbToPct = (db) => Math.max(0, Math.min(1, (db + 60) / 60)) * 100;
      let peakHold = -99;
      recorder.onLevel(({ rms, peak }) => {
        const db = rms > 0 ? 20 * Math.log10(rms) : -99;
        const pdb = peak > 0 ? 20 * Math.log10(peak) : -99;
        if (pdb > peakHold) peakHold = pdb; else peakHold -= 0.6;
        meter.style.width = dbToPct(db) + '%';
        const clip = pdb > -3;
        meterWrap.dataset.zone = clip ? 'clip' : (db < -30 ? 'low' : 'ok');
        if (vuPeak) vuPeak.style.left = dbToPct(peakHold) + '%';
        if (vuPeakDb) vuPeakDb.textContent = pdb <= -99 ? '−∞' : `${Math.round(pdb)} dB`;
        if (vuZone) vuZone.textContent = clip ? 'te hard' : (db < -30 ? 'te zacht' : 'goed');
      });
      recorder.onSourceEnded(() => {
        alert('Het delen van het vergaderingsgeluid is gestopt. Klik op "Stop & verstuur" om te versturen wat tot nu toe is opgenomen.');
      });
      await recorder.openStream();
      await refreshMics();
      $('#rec-enable').hidden = true;
      $('#rec-controls').hidden = false;
    } catch (e) {
      alert('Kon de opnamebron niet openen: ' + e.message);
    }
  });

  const stateEl = $('#rec-state');
  const stateTxt = $('#rec-state-txt');
  const discardBtn = $('#rec-discard');
  const setState = (cls, txt) => { stateEl.className = 'rec-state' + (cls ? ' ' + cls : ''); stateTxt.textContent = txt; };

  // Zet de knoppen terug naar de begin-toestand (klaar om (opnieuw) op te nemen).
  function resetRecUI() {
    clearInterval(timer);
    startBtn.hidden = false; startBtn.disabled = false;
    pauseBtn.hidden = true; pauseBtn.disabled = false; pauseBtn.textContent = '⏸ Pauzeren';
    stopBtn.hidden = true; stopBtn.disabled = false;
    discardBtn.hidden = true; discardBtn.disabled = false;
    timeEl.textContent = '00:00';
    setState('', 'Klaar om op te nemen');
  }

  startBtn.addEventListener('click', async () => {
    chunkErr = false;
    startBtn.disabled = true;
    try {
      const optimize = $('#opt-record').checked;
      const sess = await API.createSession(CONFIG.default_language, optimize, getReportConfig());
      sessionId = sess.id;
      uploadChain = Promise.resolve();
      // Chunk-callback ZETTEN vóór start(): elke chunk direct uploaden (in volgorde).
      recorder.onChunk((blob) => {
        uploadChain = uploadChain.then(() =>
          API.uploadChunk(sessionId, blob, blob.type || 'audio/webm', 'opname.webm')
            .catch((e) => { chunkErr = true; console.error(e); })
        );
      });
      recorder.start();
      startTs = Date.now();
      timer = setInterval(() => {
        const sec = Math.floor((Date.now() - startTs) / 1000);
        timeEl.textContent = `${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`;
      }, 500);
      startBtn.hidden = true;
      pauseBtn.hidden = false; stopBtn.hidden = false; discardBtn.hidden = false;
      $('#rec-download').hidden = true;
      setState('recording', 'Opnemen…');
    } catch (e) {
      alert('Kon opname niet starten: ' + e.message);
      resetRecUI();
    }
  });

  pauseBtn.addEventListener('click', () => {
    if (recorder.mediaRecorder && recorder.mediaRecorder.state === 'recording') {
      recorder.pause(); pauseBtn.textContent = '● Hervatten'; setState('paused', 'Gepauzeerd');
    } else {
      recorder.resume(); pauseBtn.textContent = '⏸ Pauzeren'; setState('recording', 'Opnemen…');
    }
  });

  stopBtn.addEventListener('click', async () => {
    stopBtn.disabled = true; pauseBtn.disabled = true; discardBtn.disabled = true;
    clearInterval(timer);
    setState('', 'Opname opslaan…');
    let blob = null, savedLocally = false;
    const saveLocalFile = () => {
      if (savedLocally || !blob) return;
      savedLocally = true;
      const url = URL.createObjectURL(blob);
      const a = el('a', { href: url, download: opnameFilename() });
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    };
    try {
      blob = await recorder.stop();
      // FOOLPROOF: sla de opname lokaal op VOORDAT we afronden. Staat de toggle aan,
      // dan gebeurt dat meteen — zo raak je de audio nooit kwijt als de upload faalt.
      if ($('#opt-savelocal').checked) saveLocalFile();
      setState('', 'Uploaden…');
      await uploadChain; // wacht tot alle gestreamde chunks binnen zijn
      if (chunkErr) throw new Error('upload van een deel van de opname is mislukt');
      await API.complete(sessionId);
      openSession(sessionId);
    } catch (e) {
      // Rescue: zorg dat de audio in elk geval lokaal is opgeslagen (ook als de toggle uit stond).
      saveLocalFile();
      alert('Verzenden mislukt: ' + e.message + '.\n\nJe opname is lokaal opgeslagen (gedownload). '
        + 'Probeer het opnieuw, of upload het gedownloade bestand later via "Bestand uploaden".');
      resetRecUI();
    }
  });

  discardBtn.addEventListener('click', async () => {
    if (!confirm('Opname weggooien? De opgenomen audio wordt niet verstuurd en direct verwijderd.')) return;
    discardBtn.disabled = true; stopBtn.disabled = true; pauseBtn.disabled = true;
    clearInterval(timer);
    setState('', 'Weggooien…');
    try { await recorder.stop(); } catch {}
    if (sessionId) { await API.deleteSession(sessionId); sessionId = null; }
    resetRecUI();
  });
}

// -------------------------------------------------------------------------
// Sessie openen: status volgen + resultaat tonen
// -------------------------------------------------------------------------
async function openSession(sessionId) {
  location.hash = 's=' + encodeURIComponent(sessionId);
  show('status');
  const box = $('#status-box');
  box.innerHTML = '';
  box.append(
    el('div', { class: 'sesh' },
      el('div', { class: 'sesh-code' },
        el('span', { class: 'lbl' }, ic('key'), ' Sessie-code (bewaar als geheim): '),
        el('code', { id: 'sid-code' }, sessionId),
      ),
      el('div', { class: 'sesh-actions' },
        el('button', { class: 'btn outline sm',
          html: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 012-2h10"/></svg> Kopieer code',
          onclick: (e) => { navigator.clipboard.writeText(sessionId); e.currentTarget.innerHTML = '✓ Gekopieerd'; } }),
        el('a', { class: 'btn outline sm', href: `/api/sessions/${sessionId}/audio`, download: '' }, ic('download'), ' Download opname'),
      ),
    ),
    el('div', { class: 'statebar' },
      el('div', { class: 'spinner', id: 'status-spinner' }),
      el('div', {},
        el('div', { class: 'txt', id: 'status-text' }, 'Laden…'),
        el('div', { class: 'wait-hint', id: 'wait-hint' }),
      ),
    ),
    el('div', { id: 'result-area' }),
  );

  // Geschatte wachttijd tonen zolang de sessie in de wachtrij/verwerking zit.
  let waitShown = false;
  const showWait = async () => {
    if (waitShown) return; waitShown = true;
    const w = await API.wait();
    const h = $('#wait-hint');
    if (w && h && w.eta_seconds > 0) {
      const m = Math.max(1, Math.round(w.eta_seconds / 60));
      h.textContent = `Geschatte wachttijd: ~${m} min (${w.queued} in de wachtrij)`;
    }
  };

  // Verbind SSE voor live updates; val terug op polling.
  if (sse) { sse.close(); sse = null; }
  let done = false;
  const render = (st) => {
    $('#status-text').textContent = STATUS_LABEL[st.status] || st.status;
    if (st.status === 'queued' || st.status === 'transcribing') {
      showWait();
    }
    if (st.status === 'transcribed' || st.status === 'failed') {
      const h = $('#wait-hint'); if (h) h.textContent = '';
      // Toon het resultaat pas als een eventueel (vooraf gevraagd) verslag óók klaar is,
      // zodat de gebruiker niet een 'klaar'-scherm ziet terwijl het verslag nog draait.
      if (!done) { done = true; finishWhenReady(sessionId); }
    }
  };
  try {
    sse = new EventSource(`/api/sessions/${sessionId}/events`);
    sse.onmessage = (e) => render(JSON.parse(e.data));
    sse.addEventListener('gone', () => { $('#status-text').textContent = 'Sessie niet gevonden of verlopen.'; sse.close(); });
    sse.onerror = () => { sse.close(); pollStatus(sessionId, render); };
  } catch {
    pollStatus(sessionId, render);
  }
}

// Wacht met het tonen van het resultaat tot transcript + (vooraf gevraagd) verslag klaar zijn.
async function finishWhenReady(sessionId) {
  const txt = $('#status-text');
  const spin = $('#status-spinner');
  const check = async () => {
    let res;
    try { res = await API.result(sessionId); }
    catch { if (txt) txt.textContent = 'Sessie niet gevonden of verlopen.'; if (spin) spin.hidden = true; return; }
    if (res.status === 'failed') { if (spin) spin.hidden = true; loadResult(sessionId); return; }
    const pending = (res.reports || []).some((r) => r.status !== 'done' && r.status !== 'failed');
    if (pending) {
      if (txt) txt.textContent = 'Transcript klaar — verslag maken…';
      setTimeout(check, 2000);
    } else {
      if (spin) spin.hidden = true;
      loadResult(sessionId);
    }
  };
  check();
}

async function pollStatus(sessionId, render) {
  const tick = async () => {
    try {
      const st = await API.status(sessionId);
      render(st);
      if (st.status !== 'transcribed' && st.status !== 'failed') setTimeout(tick, 2000);
    } catch {
      $('#status-text').textContent = 'Sessie niet gevonden of verlopen.';
    }
  };
  tick();
}

async function loadResult(sessionId) {
  let res;
  try { res = await API.result(sessionId); } catch { return; }
  setStep(3);
  const sb = document.querySelector('.statebar');
  if (sb) sb.hidden = true;   // statusbalk weg; het resultaat spreekt voor zich
  const area = $('#result-area');
  area.innerHTML = '';

  if (res.status === 'failed') {
    area.append(el('div', { class: 'error' }, 'De verwerking is mislukt: ' + (res.error || 'onbekende fout')));
    return;
  }

  area.append(el('div', { class: 'expiry-row' },
    el('div', { class: 'expiry' },
      ic('clock', 14), ` Automatisch verwijderd op ${fmtDate(res.expires_at)}.`),
    el('button', { class: 'btn ghost sm danger-text', onclick: async (e) => {
      if (!confirm('Audio, transcript én verslag nu direct verwijderen? Dit kan niet ongedaan worden gemaakt.')) return;
      e.target.disabled = true;
      await API.deleteSession(sessionId);
      location.hash = '';
      show('home');
      alert('Verwijderd. De sessie en alle gegevens zijn gewist.');
    } }, ic('trash'), ' Nu verwijderen'),
  ));

  // Twee kolommen: transcript | verslag
  const cols = el('div', { class: 'columns' });
  const left = el('div', { class: 'panel' });
  const right = el('div', { class: 'panel' });
  cols.append(left, right);
  area.append(cols);

  // Transcript
  left.append(el('div', { class: 'panel-head' },
    el('h3', {}, ic('transcript', 16), ' Transcript'),
    el('div', { class: 'panel-actions' },
      el('button', { class: 'btn outline sm', onclick: () => copy(res.transcript) }, ic('copy'), ' Kopieer'),
      el('a', { class: 'btn outline sm', href: `/api/sessions/${sessionId}/transcript.txt` }, ic('download'), ' Download .txt'),
    ),
  ));
  const tbox = el('div', { class: 'transcript' });
  tbox.textContent = res.transcript || '';
  left.append(tbox);
  if (res.segments && res.segments.length) {
    const tgl = el('button', { class: 'btn ghost sm', style: 'margin-top:10px' }, 'Toon tijdcodes');
    let showing = false;
    tgl.addEventListener('click', () => {
      showing = !showing;
      tgl.textContent = showing ? 'Verberg tijdcodes' : 'Toon tijdcodes';
      tbox.innerHTML = '';
      if (showing) {
        res.segments.forEach((s) => {
          tbox.append(el('div', { class: 'seg' },
            el('span', { class: 'ts' }, s.start != null ? `[${fmtTime(s.start)}]` : ''), ' ' + s.text));
        });
      } else { tbox.textContent = res.transcript || ''; }
    });
    left.append(tgl);
  }
  left.append(starWidget(sessionId, 'transcript', 'Hoe bruikbaar is dit transcript?'));

  // Verslag: klaargezette verslagen staan centraal; de opnieuw-maken-opties zijn ingeklapt.
  const hasReports = res.reports.length > 0;
  right.append(el('div', { class: 'panel-head' }, el('h3', {}, ic('report', 16), ' Verslag')));
  const reportsWrap = el('div', { id: 'reports-wrap' });
  right.append(reportsWrap);
  res.reports.forEach((r) => renderReport(sessionId, r, reportsWrap));

  const controls = el('details', { class: 'opts', id: 'report-controls-box', style: 'margin-top:14px' },
    el('summary', {}, hasReports ? 'Verslag opnieuw maken' : 'Verslag maken'),
    buildReportControls(sessionId),
  );
  if (!hasReports) controls.open = true;  // niets klaar -> meteen open
  right.append(controls);
  if (hasReports) right.append(starWidget(sessionId, 'verslag', 'Hoe bruikbaar is dit verslag?'));
}

function fmtTime(sec) {
  const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function buildReportControls(sessionId) {
  const wrap = el('div', { class: 'report-controls' });
  const chips = el('div', { class: 'chips' });
  const boxes = {};
  SECTIONS.filter((s) => s.key !== 'volledig').forEach((s) => {
    const cb = el('input', { type: 'checkbox' });
    boxes[s.key] = cb;
    const chip = el('label', { class: 'chip' }, cb, s.label);
    cb.addEventListener('change', () => chip.classList.toggle('on', cb.checked));
    chips.append(chip);
  });
  wrap.append(
    el('button', { class: 'btn primary block', onclick: () => start(['volledig']) }, ic('sparkle'), ' Volledig verslag (aanbevolen)'),
    el('p', { class: 'muted small', style: 'margin:2px 0' }, 'of kies losse secties:'),
    chips,
    el('button', { class: 'btn outline block', onclick: () => {
      const kinds = Object.entries(boxes).filter(([, cb]) => cb.checked).map(([k]) => k);
      if (!kinds.length) { alert('Kies minstens één sectie.'); return; }
      start(kinds);
    } }, 'Genereer gekozen secties'),
    el('details', { class: 'opts' },
      el('summary', {}, 'Eigen prompt'),
      el('textarea', { id: 'custom-prompt', rows: '3', placeholder: 'Bijv. "Vat samen in 5 bullets voor het MT."', style: 'margin:8px 0' }),
      el('button', { class: 'btn outline sm', onclick: () => {
        const t = $('#custom-prompt').value.trim();
        if (!t) { alert('Typ een prompt.'); return; }
        start(null, t);
      } }, 'Toepassen'),
    ),
    el('details', { class: 'opts' },
      el('summary', {}, 'Context meegeven (optioneel)'),
      el('textarea', { id: 'ctx', rows: '3', placeholder: 'Onderwerp, datum, deelnemers, aanleiding, achtergrond, of dingen die goed zijn om te weten. Plak hier ook gerust de agenda (dan matchen we de onderwerpen daarop)…', style: 'margin:8px 0' }),
    ),
  );

  async function start(kinds, custom) {
    const context = ($('#ctx') && $('#ctx').value.trim()) || null;
    try {
      const r = await API.createReport(sessionId, { kinds, custom_prompt: custom || null, context });
      const rw = $('#reports-wrap');
      renderReport(sessionId, r, rw, true);
    } catch (e) { alert(e.message); }
  }

  return wrap;
}

function renderReport(sessionId, report, wrap, poll = false) {
  let card = document.getElementById('rep-' + report.id);
  if (!card) {
    card = el('div', { class: 'report-card', id: 'rep-' + report.id });
    wrap.prepend(card);
  }
  const title = report.custom_prompt ? 'Eigen prompt'
    : (report.kinds || []).map((k) => (SECTIONS.find((s) => s.key === k) || {}).label || k).join(', ');
  card.innerHTML = '';
  const head = el('div', { class: 'panel-head' }, el('strong', {}, title || 'Verslag'));
  card.append(head);

  if (report.status === 'done') {
    head.append(el('div', { class: 'panel-actions' },
      el('button', { class: 'btn outline sm', onclick: () => openEditor(sessionId, report) }, ic('edit'), ' Bewerken'),
      el('button', { class: 'btn outline sm', onclick: () => copy(report.content) }, ic('copy'), ' Kopieer'),
      el('a', { class: 'btn outline sm', href: `/api/sessions/${sessionId}/reports/${report.id}/download.docx` }, ic('word'), ' Word'),
      el('a', { class: 'btn outline sm', href: `/api/sessions/${sessionId}/reports/${report.id}/download.md` }, ic('markdown'), ' Markdown'),
    ));
    const body = el('div', { class: 'report-body md' });
    body.innerHTML = renderMarkdown(report.content || '');
    card.append(body);
  } else if (report.status === 'failed') {
    card.append(el('div', { class: 'error' }, report.error || 'Verslag mislukt.'));
  } else {
    card.append(el('div', { class: 'muted small' }, ic('clock', 13), ' Bezig…'), el('progress'));
    if (poll || report.status !== 'done') pollReport(sessionId, report.id, wrap);
  }
}

async function pollReport(sessionId, reportId, wrap) {
  const tick = async () => {
    try {
      const r = await API.getReport(sessionId, reportId);
      if (r.status === 'done' || r.status === 'failed') { renderReport(sessionId, r, wrap); return; }
    } catch {}
    setTimeout(tick, 2000);
  };
  setTimeout(tick, 2000);
}

// -------------------------------------------------------------------------
// Verslag bewerken — TipTap WYSIWYG, zelf-gehost en lazy-loaded (461 KB pas
// bij openen). Opslaan gaat via PATCH; downloads/kopie weerspiegelen de tekst.
// -------------------------------------------------------------------------
let _tt = null;
async function loadTiptap() {
  if (!_tt) _tt = await import('/js/vendor/tiptap.bundle.js');
  return _tt;
}

async function openEditor(sessionId, report) {
  const modal = $('#editor-modal'), area = $('#editor-area'), tb = $('#editor-toolbar');
  const statusEl = $('#editor-status');
  area.innerHTML = ''; tb.innerHTML = ''; statusEl.textContent = 'Editor laden…';
  modal.hidden = false;

  let TT;
  try { TT = await loadTiptap(); } catch { statusEl.textContent = 'Kon de editor niet laden.'; return; }
  const { Editor, StarterKit, Markdown, Table, TableRow, TableHeader, TableCell } = TT;
  statusEl.textContent = '';

  const editor = new Editor({
    element: area,
    extensions: [StarterKit, Table.configure({ resizable: false }), TableRow, TableHeader, TableCell, Markdown],
    content: report.content || '',
  });

  const tbtns = [];
  const mk = (label, title, run, active) => {
    const b = el('button', { class: 'tb-btn', type: 'button', title,
      onclick: () => { run(editor.chain().focus()).run(); sync(); } }, label);
    b._active = active; tbtns.push(b); tb.append(b);
  };
  mk('B', 'Vet', (c) => c.toggleBold(), () => editor.isActive('bold'));
  mk('I', 'Cursief', (c) => c.toggleItalic(), () => editor.isActive('italic'));
  mk('H2', 'Kop', (c) => c.toggleHeading({ level: 2 }), () => editor.isActive('heading', { level: 2 }));
  mk('H3', 'Subkop', (c) => c.toggleHeading({ level: 3 }), () => editor.isActive('heading', { level: 3 }));
  mk('•', 'Opsomming', (c) => c.toggleBulletList(), () => editor.isActive('bulletList'));
  mk('1.', 'Genummerd', (c) => c.toggleOrderedList(), () => editor.isActive('orderedList'));
  mk('❝', 'Citaat', (c) => c.toggleBlockquote(), () => editor.isActive('blockquote'));
  mk('↶', 'Ongedaan', (c) => c.undo(), () => false);
  mk('↷', 'Opnieuw', (c) => c.redo(), () => false);
  const sync = () => tbtns.forEach((b) => b.classList.toggle('on', !!(b._active && b._active())));
  editor.on('selectionUpdate', sync); editor.on('transaction', sync); sync();

  const cleanup = () => { try { editor.destroy(); } catch {} modal.hidden = true; modal.onclick = null; };
  $('#editor-cancel').onclick = cleanup;
  $('#editor-close').onclick = cleanup;
  modal.onclick = (e) => { if (e.target === modal) cleanup(); };  // klik op de achtergrond sluit
  $('#editor-save').onclick = async () => {
    const md = editor.storage.markdown.getMarkdown();
    statusEl.textContent = 'Opslaan…';
    try {
      await API.updateReport(sessionId, report.id, md);
      report.content = md;
      const card = document.getElementById('rep-' + report.id);
      renderReport(sessionId, report, (card && card.parentNode) || $('#reports-wrap'));
      cleanup();
    } catch (e) { statusEl.textContent = e.message; }
  };
}

// -------------------------------------------------------------------------
// Ophalen via sessie-ID
// -------------------------------------------------------------------------
function setupRetrieve() {
  const doRetrieve = () => {
    const id = $('#retrieve-input').value.trim();
    if (!id) return;
    openSession(id);
  };
  $('#retrieve-btn').addEventListener('click', doRetrieve);
  $('#retrieve-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') doRetrieve(); });
  // Prominente ophaalkaart op het startscherm.
  const hb = $('#home-retrieve-btn'), hi = $('#home-retrieve-input');
  const go = () => { const id = (hi.value || '').trim(); if (id) openSession(id); };
  if (hb) hb.addEventListener('click', go);
  if (hi) hi.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
}

// Topbar verbergen bij omlaag scrollen, tonen bij omhoog (autohide).
function setupAutohideTopbar() {
  const bar = document.querySelector('.topbar');
  if (!bar) return;
  let lastY = window.scrollY || 0, ticking = false;
  const update = () => {
    const y = window.scrollY || 0;
    if (y > lastY && y > bar.offsetHeight + 8) bar.classList.add('hide');
    else if (y < lastY) bar.classList.remove('hide');
    lastY = y; ticking = false;
  };
  window.addEventListener('scroll', () => {
    if (!ticking) { requestAnimationFrame(update); ticking = true; }
  }, { passive: true });
}

// -------------------------------------------------------------------------
function copy(text) { navigator.clipboard.writeText(text || ''); }

// 1–5 sterren feedback-widget (anoniem; stuurt alleen de score).
function starWidget(sessionId, target, label) {
  const wrap = el('div', { class: 'rating' }, el('span', { class: 'rating-label' }, label));
  const stars = el('div', { class: 'stars' });
  let done = false;
  const paint = (n) => [...stars.children].forEach((s, i) => s.classList.toggle('on', i < n));
  for (let i = 1; i <= 5; i++) {
    const st = el('button', { class: 'star', title: i + ' sterren' }, '★');
    st.addEventListener('mouseenter', () => { if (!done) paint(i); });
    st.addEventListener('click', async () => {
      if (done) return; done = true; paint(i); stars.classList.add('locked');
      await API.feedback(sessionId, i, target);
      wrap.append(el('span', { class: 'rating-thanks' }, 'Bedankt voor je feedback!'));
    });
    stars.append(st);
  }
  stars.addEventListener('mouseleave', () => { if (!done) paint(0); });
  wrap.append(stars);
  return wrap;
}

init();
