import { API } from './api.js';
import { Recorder, listMics, loadSettings } from './recorder.js';
import { renderMarkdown } from './md.js';
import { url } from './base.js';

let CONFIG = { max_upload_mb: 200, retention_workdays: 2, default_language: 'nl', word_timestamps: true };
let SECTIONS = [];
let recorder = null;
let sse = null;

const $ = (sel) => document.querySelector(sel);

// Geef de microfoon/opnamebron vrij: stopt de getUserMedia-tracks + sluit de audiocontext,
// en zet de opnamekaart terug naar de "inschakelen"-staat. Aanroepen zodra je de opname
// verlaat (naar het wachtscherm, of via "Nieuw") — anders blijft de mic-indicator aan.
async function releaseRecorder() {
  if (recorder) { try { await recorder.close(); } catch {} recorder = null; }
  const ctrls = document.getElementById('rec-controls');
  const enable = document.getElementById('rec-enable');
  if (ctrls) ctrls.hidden = true;
  if (enable) enable.hidden = false;
}
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
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  users: '<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/>',
  play: '<path d="M7 4v16l13-8z"/>',
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
  fetch(url('caddy-root.crt'), { method: 'HEAD' })
    .then((r) => { if (r.ok) { const n = $('#cert-note'); if (n) n.hidden = false; } })
    .catch(() => {});

  // Sprekersidentificatie: "Geavanceerde opties" alleen tonen als de server diarisatie aan heeft.
  // Het deelnemersveld hangt aan de toggle.
  if (CONFIG.diarize_enabled) {
    const adv = $('#adv-speakers'); if (adv) adv.hidden = false;
    const dz = $('#opt-diarize'), pf = $('#participants-field');
    const syncPf = () => { if (pf) pf.hidden = !(dz && dz.checked); };
    if (dz) dz.addEventListener('change', syncPf);
    syncPf();
  }

  // Navigatie
  $('#nav-new').addEventListener('click', () => { releaseRecorder(); show('home'); });
  $('#nav-retrieve').addEventListener('click', () => show('retrieve'));

  setupConsent();
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
// Consent: toon de (configureerbare) consent-tekst in de opnamekaart. Opnemen wordt geblokkeerd
// tot de gebruiker bevestigt dat de deelnemers zijn geïnformeerd (gate in setupRecorder). Leeg -> geen stap.
function setupConsent() {
  const box = $('#rec-consent');
  const txt = $('#consent-text');
  const t = (CONFIG.consent_text || '').trim();
  if (!box || !txt || !t) return;
  txt.innerHTML = renderMarkdown(t);
  box.hidden = false;
}

function setupReportConfig() {
  const chips = $('#rep-chips');
  SECTIONS.filter((s) => s.key !== 'volledig').forEach((s) => {
    const cb = el('input', { type: 'checkbox' });
    cb.checked = true;                                  // alle onderdelen standaard aan (= volledig verslag)
    repBoxes[s.key] = cb;
    const chip = el('label', { class: 'chip on' }, cb, s.label);
    cb.addEventListener('change', () => chip.classList.toggle('on', cb.checked));
    chips.append(chip);
  });
  const applyRepMode = () => {
    const mode = (document.querySelector('input[name="rep-mode"]:checked') || {}).value || 'none';
    const opts = $('#rep-opts');
    if (opts) opts.hidden = mode === 'none';             // context + onderdelen bij 'Verslag maken'
  };
  document.querySelectorAll('input[name="rep-mode"]').forEach((r) => r.addEventListener('change', applyRepMode));
  applyRepMode();

  // Sjabloonbestand (.txt/.md/.docx/…) inlezen naar het vragen-tekstvak (docx via de server).
  const tplFile = $('#tpl-file');
  const tplText = $('#tpl-text');
  if (tplFile && tplText) {
    tplFile.addEventListener('change', async () => {
      const f = tplFile.files[0];
      if (!f) return;
      try {
        tplText.value = 'Bezig met inlezen…';
        tplText.value = await API.extractText(f);
        const w = $('#tpl-wrap'); if (w) w.open = true;
      } catch (e) {
        tplText.value = '';
        alert('Kon het sjabloonbestand niet lezen: ' + e.message);
      }
    });
  }

  // Woordenlijsten uit de plugin-map (GET /api/glossaries) in de dropdown vullen.
  const gpre = $('#glossary-preset');
  const gtext = $('#glossary-text');
  if (gpre && gtext) {
    API.glossaries().then((list) => {
      GLOSSARIES = {}; GLOSSARY_ALWAYS = [];
      (list || []).forEach(({ name, terms, always }) => {
        GLOSSARIES[name] = { terms, always: !!always };
        if (always) GLOSSARY_ALWAYS.push(name);
        gpre.append(el('option', { value: name }, always ? `${name} (altijd)` : name));
      });
    }).catch(() => { /* geen lijsten -> alleen handmatig plakken */ });
    gpre.addEventListener('change', () => {
      if (!gpre.value) { gtext.value = ''; return; }          // "— geen —"
      const cur = GLOSSARIES[gpre.value];
      if (!cur) return;
      // Domeinlijst: automatisch de 'altijd'-lijsten (algemene eigennamen) ervoor plakken.
      const parts = cur.always
        ? [cur.terms]
        : [...GLOSSARY_ALWAYS.map((n) => GLOSSARIES[n].terms), cur.terms];
      gtext.value = dedupeLines(parts.join('\n'));
      const w = $('#glossary-wrap'); if (w) w.open = true;
    });
  }
}

// Ontdubbel regels (hoofdletterongevoelig, volgorde behouden) — voor het combineren van lijsten.
function dedupeLines(s) {
  const seen = new Set(); const out = [];
  (s || '').split('\n').forEach((line) => {
    const t = line.trim(); if (!t) return;
    const k = t.toLowerCase();
    if (!seen.has(k)) { seen.add(k); out.push(t); }
  });
  return out.join('\n');
}

// Woordenlijsten uit de server-map (naam -> {terms, always}); geladen in setupReportConfig.
let GLOSSARIES = {};
let GLOSSARY_ALWAYS = [];

function getGlossary() {
  return (($('#glossary-text') || {}).value || '').trim() || null;
}

function getReportConfig() {
  const glossary = getGlossary();
  const mode = (document.querySelector('input[name="rep-mode"]:checked') || {}).value || 'none';
  // Geen verslag, maar wél een woordenlijst? Stuur alleen de glossary mee (voor de transcriptie).
  if (mode === 'none') return glossary ? { glossary } : null;
  const context = ($('#rep-context').value || '').trim() || null;
  // Sjabloon met vragen heeft voorrang: dan worden de vragen beantwoord i.p.v. een verslag.
  const template = (($('#tpl-text') || {}).value || '').trim();
  const cfg = template ? { template, context }
    : (() => {
      const kinds = Object.entries(repBoxes).filter(([, cb]) => cb.checked).map(([k]) => k);
      return kinds.length ? { kinds, context } : null;
    })();
  if (!cfg) return glossary ? { glossary } : null;       // niets aangevinkt -> hooguit de glossary
  if (glossary) cfg.glossary = glossary;
  return cfg;
}

// Gevraagd aantal deelnemers (voor sprekerherkenning); null als leeg/onzin.
function getParticipants() {
  const inp = $('#participant-count');
  if (!inp) return null;
  const v = parseInt((inp.value || '').trim(), 10);
  return Number.isFinite(v) && v > 0 ? v : null;
}

// Sprekersidentificatie aan voor deze opname? (toggle onder Geavanceerde opties; alleen zinvol
// als de server diarisatie aan heeft).
function getDiarize() {
  if (!CONFIG.diarize_enabled) return false;
  const cb = $('#opt-diarize');
  return cb ? !!cb.checked : true;
}

// -------------------------------------------------------------------------
// Bestand uploaden
// -------------------------------------------------------------------------
// Bestandsextensies die ffmpeg als audio(-drager) aankan.
const AUDIO_EXT = /\.(wav|mp3|m4a|mp4|ogg|oga|opus|webm|flac|aac|wma|aiff?|amr|mkv|mov|3gp|caf)$/i;
// Herkent audio aan MIME of extensie; wijst duidelijk niet-audio (Word/PDF/beeld/tekst) af.
function looksLikeAudio(file) {
  if (!file) return false;
  const name = (file.name || '').toLowerCase();
  const type = (file.type || '').toLowerCase();
  // audio/* en video/* (containers met een audiospoor) mogen — ffmpeg pakt de audio eruit.
  if (type.startsWith('audio/') || type.startsWith('video/')) return true;
  // Onbekend/leeg MIME: vertrouw op de extensie.
  if (!type) return AUDIO_EXT.test(name);
  // Bekend maar niet-audio MIME (application/pdf, .docx, image/*, text/*): alleen als de
  // extensie tóch audio is (zeldzaam); anders afwijzen.
  return AUDIO_EXT.test(name);
}
const NOT_AUDIO_MSG = 'Dit lijkt geen audiobestand. Upload een audio-opname (wav, mp3, m4a, ogg, webm, flac …). '
  + 'Een Word/PDF/tekstbestand kan hier niet — kies bovenaan "Transcript of aantekeningen".';
// Tekstbestanden die het tekst-endpoint kan lezen (pandoc voor docx/rtf/odt).
const TEXT_EXT = /\.(txt|md|markdown|docx|rtf|odt|doc|html|htm)$/i;

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
      if (!looksLikeAudio(f)) { alert(NOT_AUDIO_MSG); return; }  // drag-&-drop negeert accept -> zelf checken
      try { const dt = new DataTransfer(); dt.items.add(f); input.files = dt.files; }
      catch { /* oudere browser: file-input laat 'm dan zelf niet zetten */ }
    });
  }

  // Audio- vs tekst-tak wisselen.
  const upAudio = $('#up-audio');
  const upText = $('#up-text');
  const currentKind = () => (document.querySelector('input[name="up-kind"]:checked') || {}).value || 'audio';
  const applyKind = () => {
    const k = currentKind();
    if (upAudio) upAudio.hidden = k !== 'audio';
    if (upText) upText.hidden = k !== 'text';
  };
  document.querySelectorAll('input[name="up-kind"]').forEach((r) => r.addEventListener('change', applyKind));
  applyKind();

  // Tekst (aantekeningen/transcript) -> sessie zonder audio/STT.
  async function submitText() {
    const tfile = ($('#text-file').files || [])[0] || null;
    const ttext = ($('#text-input').value || '').trim();
    if (!tfile && !ttext) { alert('Plak of upload eerst tekst (aantekeningen of een transcript).'); return; }
    if (tfile && !TEXT_EXT.test(tfile.name || '')) {
      alert('Kies een tekstbestand (.txt, .md, Word/.docx, .rtf of .odt) — of plak de tekst in het vak.');
      return;
    }
    if (tfile && tfile.size > CONFIG.max_upload_mb * 1024 * 1024) {
      alert(`Bestand te groot (max ${CONFIG.max_upload_mb} MB).`); return;
    }
    const sourceKind = (document.querySelector('input[name="txt-kind"]:checked') || {}).value || 'notes';
    btn.disabled = true;
    try {
      const res = await API.createTextSession(tfile, ttext, CONFIG.default_language, getReportConfig(), sourceKind);
      openSession(res.id);
    } catch (e) {
      alert('Verwerken mislukt: ' + e.message);
    } finally {
      btn.disabled = false;
    }
  }

  btn.addEventListener('click', async () => {
    if (currentKind() === 'text') { await submitText(); return; }
    const file = input.files[0];
    if (!file) { alert('Kies eerst een bestand.'); return; }
    if (!looksLikeAudio(file)) { alert(NOT_AUDIO_MSG); return; }
    const maxBytes = CONFIG.max_upload_mb * 1024 * 1024;
    if (file.size > maxBytes) { alert(`Bestand te groot (max ${CONFIG.max_upload_mb} MB).`); return; }
    const optimize = $('#opt-upload').checked;
    btn.disabled = true;
    prog.hidden = false;
    try {
      const res = await API.uploadFileChunked(file, CONFIG.default_language, optimize, getReportConfig(), (f) => {
        prog.value = Math.round(f * 100);
      }, getParticipants(), getDiarize());
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
    // Consent-gate: opnemen kan pas ná expliciete bevestiging (alleen als er een consent-tekst is).
    const consentBox = $('#rec-consent');
    const ack = $('#consent-ack');
    if (consentBox && !consentBox.hidden && ack && !ack.checked) {
      alert('Vraag eerst toestemming aan de deelnemers en vink dat aan voordat je opneemt.');
      consentBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    chunkErr = false;
    startBtn.disabled = true;
    try {
      const optimize = $('#opt-record').checked;
      const sess = await API.createSession(CONFIG.default_language, optimize, getReportConfig(), getParticipants(), getDiarize());
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
      await releaseRecorder();   // microfoon vrijgeven vóór het wachtscherm
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
        el('a', { class: 'btn outline sm', href: url(`api/sessions/${sessionId}/audio`), download: '' }, ic('download'), ' Download opname'),
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
    const t = $('#status-text');
    if (st.status === 'queued') {                              // fase 1
      t.textContent = st.queue_position
        ? `Transcriptie is nummer ${st.queue_position} in de wachtrij`
        : 'Transcriptie staat in de wachtrij';
      setSttProgress(null);
      showWait();
    } else if (st.status === 'transcribing') {                 // fase 2
      const pct = (typeof st.progress === 'number') ? Math.round(st.progress * 100) : null;
      t.textContent = pct !== null ? `Transcriptie wordt gemaakt… ${pct}%` : 'Transcriptie wordt gemaakt…';
      setSttProgress(pct);
      showWait();
    } else if (st.status === 'transcribed' || st.status === 'failed') {
      setSttProgress(null);
      const h = $('#wait-hint'); if (h) h.textContent = '';
      // Toon het resultaat pas als een eventueel (vooraf gevraagd) verslag óók klaar is,
      // zodat de gebruiker niet een 'klaar'-scherm ziet terwijl het verslag nog draait.
      if (!done) { done = true; finishWhenReady(sessionId); }
    } else {
      t.textContent = STATUS_LABEL[st.status] || st.status;
    }
  };
  try {
    sse = new EventSource(url(`api/sessions/${sessionId}/events`));
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
    const pending = (res.reports || []).filter((r) => r.status !== 'done' && r.status !== 'failed');
    if (pending.length) {
      const r = pending[0];
      if (txt) {
        if (r.status === 'running') {                          // fase 4
          txt.textContent = 'Verslag wordt gemaakt…';
        } else {                                                // fase 3 (queued)
          txt.textContent = r.queue_position
            ? `Transcript klaar. Verslag is nummer ${r.queue_position} in de wachtrij`
            : 'Transcript klaar. Verslag staat in de wachtrij';
        }
      }
      setTimeout(check, 2000);
    } else {
      if (spin) spin.hidden = true;
      loadResult(sessionId);
    }
  };
  check();
}

// Toon/actualiseer de transcriptie-voortgangsbalk in de statebar. pct=null verwijdert 'm.
function setSttProgress(pct) {
  let bar = document.getElementById('stt-progress');
  if (pct === null || pct === undefined || isNaN(pct)) { if (bar) bar.remove(); return; }
  if (!bar) {
    const anchor = document.getElementById('status-text');
    if (!anchor || !anchor.parentNode) return;
    bar = el('progress', { id: 'stt-progress', max: '100', style: 'width:100%;margin-top:8px;display:block' });
    anchor.parentNode.appendChild(bar);
  }
  bar.value = Math.max(0, Math.min(100, pct));
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
  CURRENT_RES = res;
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
      el('a', { class: 'btn outline sm', href: url(`api/sessions/${sessionId}/transcript.txt`) }, ic('download'), ' Download .txt'),
    ),
  ));
  const tbox = el('div', { class: 'transcript' });
  renderTranscriptBody(tbox, res, loadSpeakerNames(sessionId));
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
      } else { renderTranscriptBody(tbox, res, loadSpeakerNames(sessionId)); }
    });
    left.append(tgl);
  }
  // Sprekers-blok (alleen als de server diarisatie aan heeft en er een diarisatie is).
  if (CONFIG.diarize_enabled && res.diarization) {
    const sb = buildSpeakersBlock(sessionId, res);
    if (sb) left.append(sb);
  }
  left.append(starWidget(sessionId, 'transcript', 'Hoe bruikbaar is dit transcript?'));

  // Verslag: klaargezette verslagen staan centraal; de opnieuw-maken-opties zijn ingeklapt.
  const hasReports = res.reports.length > 0;
  right.append(el('div', { class: 'panel-head' }, el('h3', {}, ic('report', 16), ' Verslag')));
  const reportsWrap = el('div', { id: 'reports-wrap' });
  right.append(reportsWrap);
  REPORTS = (res.reports || []).slice();
  layoutReports(sessionId);

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

// -------------------------------------------------------------------------
// Sprekers: namen (localStorage per sessie), label->naam-substitutie, weergave
// -------------------------------------------------------------------------
let CURRENT_RES = null;                       // laatst geladen resultaat (voor herrenderen bij naamswijziging)
const speakersKey = (sid) => `transcribe.speakers.${sid}`;
function loadSpeakerNames(sid) {
  try { return JSON.parse(localStorage.getItem(speakersKey(sid)) || '{}') || {}; } catch { return {}; }
}
function saveSpeakerNames(sid, map) { localStorage.setItem(speakersKey(sid), JSON.stringify(map)); }
function hasSpeakerNames(names) { return Object.values(names || {}).some((v) => v && String(v).trim()); }

// Vervang de labels SPREKER_A/B/… door de ingevulde namen. \b voorkomt dat SPREKER_A
// binnen SPREKER_AA raakt; lege namen laten het label ongemoeid.
function applySpeakerNames(text, names) {
  if (!text || !names) return text || '';
  let out = text;
  for (const [label, name] of Object.entries(names)) {
    const nm = (name || '').trim();
    if (nm) out = out.replace(new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b', 'g'), nm);
  }
  return out;
}

// Startseconde van het langste segment van een spreker (voor het luisterfragment).
function longestSegmentStart(segments, speaker) {
  let best = null, bestDur = -1;
  (segments || []).forEach((s) => {
    if (s.speaker === speaker && s.start != null && s.end != null && (s.end - s.start) > bestDur) {
      bestDur = s.end - s.start; best = s.start;
    }
  });
  return best;
}

let _snipTimer = null;
function playSnippet(audio, start, seconds = 3) {
  if (!audio || start == null) return;
  clearTimeout(_snipTimer);
  const go = () => {
    try {
      audio.currentTime = start;
      audio.play().then(() => { _snipTimer = setTimeout(() => audio.pause(), seconds * 1000); }).catch(() => {});
    } catch {}
  };
  audio.pause();
  if (audio.readyState >= 1) { go(); }          // metadata al binnen -> direct seeken
  else { audio.preload = 'metadata'; audio.addEventListener('loadedmetadata', go, { once: true }); audio.load(); }
}

// Vul de transcript-box: met diarisatie -> sprekerlabels/namen per beurt; anders platte tekst.
function renderTranscriptBody(tbox, res, names) {
  const diar = res && res.diarization;
  if (diar && diar.status === 'done' && diar.segments && diar.segments.length) {
    tbox.innerHTML = '';
    diar.segments.forEach((seg) => {
      const row = el('div', { class: 'turn' });
      if (seg.speaker) row.append(el('span', { class: 'spk' }, (names[seg.speaker] || seg.speaker) + ': '));
      row.append(document.createTextNode(seg.text || ''));
      tbox.append(row);
    });
  } else {
    tbox.textContent = res.transcript || '';
  }
}

// Na een naamswijziging: transcript + verslagen opnieuw renderen (labels -> namen).
function refreshSpeakerLabels(sessionId) {
  const tbox = document.querySelector('#result-area .transcript');
  if (tbox && CURRENT_RES) renderTranscriptBody(tbox, CURRENT_RES, loadSpeakerNames(sessionId));
  layoutReports(sessionId);
}

// Het "Sprekers"-blok op de resultaatpagina (alleen als diarisatie aan staat en er data is).
function buildSpeakersBlock(sessionId, res) {
  const diar = res.diarization;
  if (!diar) return null;
  const names = loadSpeakerNames(sessionId);
  const panel = el('div', { class: 'panel speakers', id: 'speakers-block' });
  panel.append(el('div', { class: 'panel-head' }, el('h3', {}, ic('users', 16), ' Sprekers')));
  const info = el('div', { class: 'muted small', style: 'margin-bottom:10px' });
  panel.append(info);

  if (diar.status !== 'done') {
    info.textContent = diar.status === 'failed'
      ? 'Sprekersherkenning is mislukt — het transcript blijft gewoon bruikbaar.'
      : 'Sprekers worden ingedeeld…';
    if (diar.status !== 'failed') pollDiarization(sessionId);
  } else if (!diar.speakers || !diar.speakers.length) {
    info.textContent = 'Geen aparte sprekers gevonden.';
  } else {
    info.textContent = `${diar.num_speakers || diar.speakers.length} spreker(s) herkend. Vul namen in (optioneel) — ze worden lokaal bewaard en in de weergave en het verslag gebruikt.`;
    const audio = el('audio', { src: url(`api/sessions/${sessionId}/audio`), preload: 'none' });
    const rows = el('div', { class: 'speaker-rows' });
    const clips = diar.clips || {};
    diar.speakers.forEach((label) => {
      // Slim fragment: langste aaneengesloten spraak (server); val terug op het langste segment.
      const clip = clips[label];
      const start = clip ? clip[0] : longestSegmentStart(diar.segments, label);
      const dur = clip ? Math.max(1, Math.round(clip[1] - clip[0])) : 3;
      const play = el('button', { class: 'btn outline sm', title: `Luister ~${dur} s van deze spreker`,
        onclick: () => playSnippet(audio, start, dur) }, ic('play', 13), ` ${dur}s`);
      if (start == null) play.disabled = true;
      const input = el('input', { type: 'text', class: 'spk-name mono', value: names[label] || '', placeholder: 'naam…' });
      input.addEventListener('input', () => {
        names[label] = input.value; saveSpeakerNames(sessionId, names); refreshSpeakerLabels(sessionId);
      });
      rows.append(el('div', { class: 'speaker-row' }, el('span', { class: 'spk-label' }, label), play, input));
    });
    panel.append(rows, audio);
  }

  // Opnieuw indelen (nieuwe diarisatie op hetzelfde transcript + audio).
  const redo = el('details', { class: 'opts', style: 'margin-top:12px' },
    el('summary', {}, 'Opnieuw indelen'));
  const cnt = el('input', { type: 'number', min: '1', max: '20', step: '1', class: 'mono',
    style: 'width:120px', placeholder: 'aantal' });
  const btn = el('button', { class: 'btn outline sm', onclick: async () => {
    btn.disabled = true;
    const v = parseInt((cnt.value || '').trim(), 10);
    try {
      await API.rediarize(sessionId, Number.isFinite(v) && v > 0 ? v : null);
      info.textContent = 'Sprekers worden opnieuw ingedeeld…';
      pollDiarization(sessionId);
    } catch (e) { alert(e.message); btn.disabled = false; }
  } }, 'Start opnieuw indelen');
  redo.append(el('p', { class: 'muted small', style: 'margin:8px 0' },
    'Draait alléén de sprekersherkenning opnieuw op dit transcript. Geef eventueel een ander aantal deelnemers op.'),
    el('div', { class: 'redo-row' }, cnt, btn));
  panel.append(redo);
  return panel;
}

// Poll de diarisatie-status tot done/failed en herlaad dan het resultaat.
let _diarPoll = null;
function pollDiarization(sessionId) {
  clearTimeout(_diarPoll);
  const tick = async () => {
    let res;
    try { res = await API.result(sessionId); } catch { return; }
    const st = res.diarization && res.diarization.status;
    if (st === 'done' || st === 'failed') { loadResult(sessionId); return; }
    _diarPoll = setTimeout(tick, 2500);
  };
  _diarPoll = setTimeout(tick, 2500);
}

// Client-side export met ingevulde namen (namen komen zo niet in de DB).
function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = el('a', { href: url, download: filename });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
function exportReportMd(sessionId, report) {
  const content = applySpeakerNames(report.content || '', loadSpeakerNames(sessionId));
  downloadBlob(new Blob([content], { type: 'text/markdown' }), `verslag-${report.id.slice(0, 8)}.md`);
}
async function exportReportDocx(sessionId, report, btn) {
  const content = applySpeakerNames(report.content || '', loadSpeakerNames(sessionId));
  if (btn) btn.disabled = true;
  try { downloadBlob(await API.convertDocx(content), `verslag-${report.id.slice(0, 8)}.docx`); }
  catch (e) { alert(e.message); }
  finally { if (btn) btn.disabled = false; }
}

function buildReportControls(sessionId) {
  const wrap = el('div', { class: 'report-controls' });
  const chips = el('div', { class: 'chips' });
  const boxes = {};
  SECTIONS.filter((s) => s.key !== 'volledig').forEach((s) => {
    const cb = el('input', { type: 'checkbox' });
    cb.checked = true;                                  // alles aan = volledig verslag
    boxes[s.key] = cb;
    const chip = el('label', { class: 'chip on' }, cb, s.label);
    cb.addEventListener('change', () => chip.classList.toggle('on', cb.checked));
    chips.append(chip);
  });
  wrap.append(
    el('p', { class: 'context-tip' }, el('strong', {}, 'Tip — geef context mee.'),
      ' Onderwerp, datum, deelnemers, aanleiding/achtergrond of de agenda verbeteren het verslag merkbaar: correcte namen, structuur volgens je agenda en minder giswerk.'),
    el('textarea', { id: 'ctx', rows: '3', placeholder: 'Context (optioneel, maar sterk aanbevolen) — onderwerp, datum, deelnemers, aanleiding, achtergrond, of de agenda (dan matchen we de onderwerpen daarop)…' }),
    el('p', { class: 'muted small', style: 'margin:14px 0 6px' }, 'Onderdelen — alles aan = een volledig verslag:'),
    chips,
    el('button', { class: 'btn primary block', style: 'margin-top:12px', onclick: () => {
      const kinds = Object.entries(boxes).filter(([, cb]) => cb.checked).map(([k]) => k);
      if (!kinds.length) { alert('Kies minstens één onderdeel.'); return; }
      start(kinds);
    } }, ic('sparkle'), ' Verslag genereren'),
    el('div', { class: 'or-sep' }, 'of'),
    el('textarea', { id: 'custom-prompt', rows: '3', placeholder: 'Eigen prompt — bijv. "Vat samen in 5 bullets voor het MT." (de context hierboven wordt meegenomen)' }),
    el('button', { class: 'btn outline block', style: 'margin-top:10px', onclick: () => {
      const t = $('#custom-prompt').value.trim();
      if (!t) { alert('Typ een prompt.'); return; }
      start(null, t);
    } }, 'Voer prompt uit'),
    el('div', { class: 'or-sep' }, 'of'),
    el('textarea', { id: 'tpl-prompt', rows: '3', placeholder: 'Vragen uit een sjabloon (één per regel) — elke vraag wordt beantwoord op basis van het gesprek, in plaats van een verslag.' }),
    el('button', { class: 'btn outline block', style: 'margin-top:10px', onclick: () => {
      const t = $('#tpl-prompt').value.trim();
      if (!t) { alert('Plak eerst een of meer vragen.'); return; }
      start(null, null, t);
    } }, 'Beantwoord de vragen'),
  );

  async function start(kinds, custom, template) {
    const context = ($('#ctx') && $('#ctx').value.trim()) || null;
    try {
      const r = await API.createReport(sessionId, { kinds, custom_prompt: custom || null, context, template: template || null });
      REPORTS.push(r);
      layoutReports(sessionId);
    } catch (e) { alert(e.message); }
  }

  return wrap;
}

// De verslagen-kolom: het nieuwste verslag staat open bovenaan; oudere verslagen
// staan ingeklapt onder "Eerdere verslagen". REPORTS is de client-side lijst die
// bij aanmaken, pollen, bewerken en verwijderen wordt bijgewerkt.
let REPORTS = [];

function layoutReports(sessionId) {
  const wrap = $('#reports-wrap');
  if (!wrap) return;
  wrap.innerHTML = '';
  const sorted = REPORTS.slice().sort((a, b) => (a.created_at < b.created_at ? 1 : -1));  // nieuwste eerst
  if (!sorted.length) return;
  const [latest, ...older] = sorted;
  renderReportCard(sessionId, latest, wrap);
  if (older.length) {
    const det = el('details', { class: 'opts older-reports', style: 'margin-top:12px' },
      el('summary', {}, `Eerdere verslagen (${older.length})`));
    older.forEach((r) => renderReportCard(sessionId, r, det));
    wrap.append(det);
  }
}

async function deleteReport(sessionId, report) {
  if (!confirm('Dit verslag verwijderen? Dit kan niet ongedaan worden gemaakt.')) return;
  try {
    await API.deleteReport(sessionId, report.id);
    REPORTS = REPORTS.filter((r) => r.id !== report.id);
    layoutReports(sessionId);
  } catch (e) { alert(e.message); }
}

function renderReportCard(sessionId, report, parent) {
  const card = el('div', { class: 'report-card', id: 'rep-' + report.id });
  const title = report.custom_prompt ? 'Eigen prompt'
    : (report.kinds || []).map((k) => (SECTIONS.find((s) => s.key === k) || {}).label || k).join(', ');
  const names = loadSpeakerNames(sessionId);
  const named = hasSpeakerNames(names);        // namen ingevuld -> client-side export met substitutie
  const actions = el('div', { class: 'panel-actions' });
  if (report.status === 'done') {
    const wordBtn = named
      ? el('button', { class: 'btn outline sm', onclick: (e) => exportReportDocx(sessionId, report, e.currentTarget) }, ic('word'), ' Word')
      : el('a', { class: 'btn outline sm', href: url(`api/sessions/${sessionId}/reports/${report.id}/download.docx`) }, ic('word'), ' Word');
    const mdBtn = named
      ? el('button', { class: 'btn outline sm', onclick: () => exportReportMd(sessionId, report) }, ic('markdown'), ' Markdown')
      : el('a', { class: 'btn outline sm', href: url(`api/sessions/${sessionId}/reports/${report.id}/download.md`) }, ic('markdown'), ' Markdown');
    actions.append(
      el('button', { class: 'btn outline sm', onclick: () => openEditor(sessionId, report) }, ic('edit'), ' Bewerken'),
      el('button', { class: 'btn outline sm', onclick: () => copy(applySpeakerNames(report.content, names)) }, ic('copy'), ' Kopieer'),
      wordBtn, mdBtn,
    );
  }
  // Verwijderknop (X) rechtsboven — altijd beschikbaar.
  actions.append(el('button', {
    class: 'btn ghost sm icon report-del', title: 'Verslag verwijderen',
    'aria-label': 'Verslag verwijderen', onclick: () => deleteReport(sessionId, report),
  }, ic('close', 15)));
  card.append(el('div', { class: 'panel-head' }, el('strong', {}, title || 'Verslag'), actions));

  if (report.status === 'done') {
    const body = el('div', { class: 'report-body md' });
    body.innerHTML = renderMarkdown(applySpeakerNames(report.content || '', names));
    card.append(body);
  } else if (report.status === 'failed') {
    card.append(el('div', { class: 'error' }, report.error || 'Verslag mislukt.'));
  } else {
    card.append(el('div', { class: 'muted small' }, ic('clock', 13), ' Bezig…'), el('progress'));
    pollReport(sessionId, report.id);
  }
  parent.append(card);
}

async function pollReport(sessionId, reportId) {
  const tick = async () => {
    try {
      const r = await API.getReport(sessionId, reportId);
      if (r.status === 'done' || r.status === 'failed') {
        const i = REPORTS.findIndex((x) => x.id === reportId);
        if (i >= 0) REPORTS[i] = r; else REPORTS.push(r);
        layoutReports(sessionId);
        return;
      }
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
  if (!_tt) _tt = await import(url('js/vendor/tiptap.bundle.js'));
  return _tt;
}

// Vervang ALLE exacte voorkomens van `find` door `replace` in de ProseMirror-doc.
// Handig voor namen die consequent verkeerd staan. Behoudt opmaak; geeft het aantal terug.
function editorReplaceAll(editor, find, replace) {
  if (!find) return 0;
  const { state } = editor;
  const ranges = [];
  state.doc.descendants((node, pos) => {
    if (node.isText && node.text) {
      const t = node.text;
      let i = 0;
      while ((i = t.indexOf(find, i)) !== -1) { ranges.push([pos + i, pos + i + find.length]); i += find.length; }
    }
  });
  if (!ranges.length) return 0;
  let tr = state.tr;
  // Van achter naar voren, zodat eerdere posities geldig blijven.
  for (let k = ranges.length - 1; k >= 0; k--) tr = tr.insertText(replace, ranges[k][0], ranges[k][1]);
  editor.view.dispatch(tr);
  return ranges.length;
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

  // Zoek & vervang (alles) — handig voor consequent verkeerd gespelde namen.
  const fbox = $('#editor-find');
  if (fbox) {
    fbox.innerHTML = '';
    const findIn = el('input', { type: 'text', class: 'mono', placeholder: 'Zoek…', 'aria-label': 'Zoeken' });
    const replIn = el('input', { type: 'text', class: 'mono', placeholder: 'Vervang door…', 'aria-label': 'Vervang door' });
    const info = el('span', { class: 'muted small ef-info' });
    const doIt = () => {
      const f = findIn.value;
      if (!f) { info.textContent = ''; return; }
      const n = editorReplaceAll(editor, f, replIn.value);
      info.textContent = n ? `${n}× vervangen` : 'niet gevonden';
    };
    replIn.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); doIt(); } });
    fbox.append(
      el('span', { class: 'ef-label' }, 'Zoek & vervang'),
      findIn, replIn,
      el('button', { class: 'btn outline sm', type: 'button', onclick: doIt }, 'Vervang alles'),
      info,
    );
  }

  const cleanup = () => { try { editor.destroy(); } catch {} modal.hidden = true; modal.onclick = null; };
  $('#editor-cancel').onclick = cleanup;
  $('#editor-close').onclick = cleanup;
  modal.onclick = (e) => { if (e.target === modal) cleanup(); };  // klik op de achtergrond sluit
  $('#editor-save').onclick = async () => {
    const md = editor.storage.markdown.getMarkdown();
    statusEl.textContent = 'Opslaan…';
    try {
      const updated = await API.updateReport(sessionId, report.id, md);
      report.content = md;
      const i = REPORTS.findIndex((x) => x.id === report.id);
      if (i >= 0) REPORTS[i] = updated;
      layoutReports(sessionId);
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
