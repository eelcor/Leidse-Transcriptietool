// Browser-recorder met Web Audio-keten, VU-meter en spraakgerichte DSP.
//
// Keten:  getUserMedia(constraints: AGC/echo/noise) -> MediaStreamSource
//         -> [highpass ~80Hz] -> GainNode (sensitivity) -> AnalyserNode (VU)
//         -> MediaStreamDestination -> MediaRecorder (Opus/WebM, mono, ~32kbps)
//
// BELANGRIJK: geen agressieve spectrale denoising. De veilige default is
// browser-AGC + lichte noiseSuppression + hoogdoorlaat. Dit beschermt de WER.

const LS_KEY = 'transcribe.recorder.settings.v1';

export const defaultSettings = {
  deviceId: '',
  source: 'mic',    // 'mic' | 'system' (tab/scherm, bijv. Teams) | 'both'
  autoGainControl: true,
  echoCancellation: true,
  noiseSuppression: true,
  highpass: true,
  gain: 1.0,        // handmatige gevoeligheid (fijnafstemming)
  vadTrim: false,   // optioneel; client-side stilte trimmen (stub-hint)
  bitrate: 48000,   // Opus-bitrate; 48 kbps = goede balans voor vergaderingen
  saveLocal: true,  // opname ook lokaal downloaden (standaard AAN: voorkomt verlies bij vergeten code)
};

export function loadSettings() {
  try {
    return { ...defaultSettings, ...JSON.parse(localStorage.getItem(LS_KEY) || '{}') };
  } catch { return { ...defaultSettings }; }
}
export function saveSettings(s) {
  localStorage.setItem(LS_KEY, JSON.stringify(s)); // alleen client-side (anonimiteit)
}

export async function listMics() {
  // Labels zijn pas beschikbaar na permissie; roep na getUserMedia opnieuw aan.
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices.filter((d) => d.kind === 'audioinput');
}

function pickMimeType() {
  const prefs = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'];
  for (const t of prefs) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(t)) return t;
  }
  return '';
}

export class Recorder {
  constructor() {
    this.settings = loadSettings();
    this.audioCtx = null;
    this.rawStream = null;
    this.source = null;
    this.highpass = null;
    this.gainNode = null;
    this.analyser = null;
    this.destNode = null;
    this.mediaRecorder = null;
    this.mimeType = '';
    this.chunks = [];       // voor lokale download-blob
    this._levelCb = null;
    this._rafId = null;
    this._streams = [];     // alle actieve capture-streams (mic en/of display)
    this._onSourceEnded = null;
  }

  onLevel(cb) { this._levelCb = cb; }
  onSourceEnded(cb) { this._onSourceEnded = cb; }

  async openStream() {
    // Sluit eventuele bestaande stream (bron/constraints gewijzigd).
    await this._teardownStream();
    const s = this.settings;
    const src = s.source || 'mic';

    this.audioCtx = this.audioCtx || new (window.AudioContext || window.webkitAudioContext)();

    // Vaste staart van de keten: gain (gevoeligheid) -> analyser (VU) -> destination (recorder).
    this.gainNode = this.audioCtx.createGain();
    this.gainNode.gain.value = s.gain;
    this.analyser = this.audioCtx.createAnalyser();
    this.analyser.fftSize = 1024;
    this.destNode = this.audioCtx.createMediaStreamDestination();
    this.gainNode.connect(this.analyser);
    this.analyser.connect(this.destNode);

    // Hoogdoorlaat (~80 Hz) alleen op de microfoon; systeemgeluid gaat rechtstreeks.
    this.highpass = this.audioCtx.createBiquadFilter();
    this.highpass.type = 'highpass';
    this.highpass.frequency.value = s.highpass ? 80 : 0;
    this.highpass.connect(this.gainNode);

    this._streams = [];
    this.rawStream = null;

    // --- Microfoon ---
    if (src === 'mic' || src === 'both') {
      const audio = {
        autoGainControl: !!s.autoGainControl,
        echoCancellation: !!s.echoCancellation,
        noiseSuppression: !!s.noiseSuppression,
        channelCount: 1,
      };
      if (s.deviceId) audio.deviceId = { exact: s.deviceId };
      const mic = await navigator.mediaDevices.getUserMedia({ audio });
      this._streams.push(mic);
      this.rawStream = mic;   // t.b.v. microfoon-labels (enumerateDevices)
      this.audioCtx.createMediaStreamSource(mic).connect(this.highpass);
    }

    // --- Vergaderings-/systeemgeluid (tab of scherm, bijv. Teams) via getDisplayMedia ---
    if (src === 'system' || src === 'both') {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
        await this._teardownStream();
        throw new Error('Deze browser kan geen tab-/systeemgeluid delen. Gebruik Chrome of Edge.');
      }
      let disp;
      try {
        // video is verplicht bij getDisplayMedia; we gebruiken alleen het audiospoor.
        disp = await navigator.mediaDevices.getDisplayMedia({
          video: true,
          audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
        });
      } catch {
        await this._teardownStream();
        throw new Error('Delen geannuleerd. Kies het Teams-venster of -tabblad om het geluid op te nemen.');
      }
      const aTracks = disp.getAudioTracks();
      if (!aTracks.length) {
        disp.getTracks().forEach((t) => t.stop());
        await this._teardownStream();
        throw new Error('Geen geluid gedeeld. Vink bij het delen "Ook tabblad-/systeemgeluid delen" aan.');
      }
      this._streams.push(disp);   // hele stream vasthouden (incl. video), anders stopt de capture
      if (!this.rawStream) this.rawStream = disp;
      // Alleen het audiospoor door de keten; systeemgeluid gaat direct naar gain (geen hoogdoorlaat).
      this.audioCtx.createMediaStreamSource(new MediaStream(aTracks)).connect(this.gainNode);
      // Stopt de gebruiker het delen via de browserbalk, meld dat aan de app.
      aTracks[0].addEventListener('ended', () => { if (this._onSourceEnded) this._onSourceEnded(); });
    }

    this._startMeter();
    return this.rawStream;
  }

  setGain(v) {
    this.settings.gain = v;
    if (this.gainNode) this.gainNode.gain.value = v;
    saveSettings(this.settings);
  }

  setBitrate(v) {
    this.settings.bitrate = v;   // geldt vanaf de volgende opname
    saveSettings(this.settings);
  }

  setHighpass(on) {
    this.settings.highpass = on;
    if (this.highpass) this.highpass.frequency.value = on ? 80 : 0;
    saveSettings(this.settings);
  }

  async applyConstraints(partial) {
    Object.assign(this.settings, partial);
    saveSettings(this.settings);
    // AGC/echo/noise/device vereisen een nieuwe getUserMedia.
    if (this.rawStream) await this.openStream();
  }

  _startMeter() {
    const buf = new Float32Array(this.analyser.fftSize);
    const tick = () => {
      this.analyser.getFloatTimeDomainData(buf);
      let sum = 0, peak = 0;
      for (let i = 0; i < buf.length; i++) {
        const v = buf[i];
        sum += v * v;
        if (Math.abs(v) > peak) peak = Math.abs(v);
      }
      const rms = Math.sqrt(sum / buf.length);
      if (this._levelCb) this._levelCb({ rms, peak });
      this._rafId = requestAnimationFrame(tick);
    };
    cancelAnimationFrame(this._rafId);
    tick();
  }

  start() {
    this.chunks = [];
    this.mimeType = pickMimeType();
    const opts = { audioBitsPerSecond: this.settings.bitrate || 48000 };
    if (this.mimeType) opts.mimeType = this.mimeType;
    this.mediaRecorder = new MediaRecorder(this.destNode.stream, opts);
    // NIET this._ondata resetten: de app zet de chunk-callback via onChunk() vóór start().
    this.mediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) {
        this.chunks.push(e.data);
        if (this._ondata) this._ondata(e.data);
      }
    };
    // timeslice: lever elke 5s een chunk voor robuuste chunked upload.
    this.mediaRecorder.start(5000);
  }

  onChunk(cb) { this._ondata = cb; }

  pause() { if (this.mediaRecorder && this.mediaRecorder.state === 'recording') this.mediaRecorder.pause(); }
  resume() { if (this.mediaRecorder && this.mediaRecorder.state === 'paused') this.mediaRecorder.resume(); }

  stop() {
    return new Promise((resolve) => {
      if (!this.mediaRecorder) return resolve(null);
      this.mediaRecorder.onstop = () => {
        const blob = new Blob(this.chunks, { type: this.mimeType || 'audio/webm' });
        resolve(blob);
      };
      this.mediaRecorder.stop();
    });
  }

  async _teardownStream() {
    if (this._rafId) cancelAnimationFrame(this._rafId);
    for (const st of this._streams || []) {
      try { st.getTracks().forEach((t) => t.stop()); } catch {}
    }
    this._streams = [];
    this.rawStream = null;
  }

  async close() {
    await this._teardownStream();
    if (this.audioCtx) { try { await this.audioCtx.close(); } catch {} this.audioCtx = null; }
  }
}
