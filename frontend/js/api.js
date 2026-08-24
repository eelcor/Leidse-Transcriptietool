// Dunne API-client. Alle calls gaan naar <basispad>/api (Caddy proxyt naar de FastAPI-service).
// url() voorziet het app-basispad zodat de app ook onder een reverse-proxy-subpad werkt.
import { url } from './base.js';

export const API = {
  async config() {
    return (await fetch(url('api/config'))).json();
  },
  async prompts() {
    return (await fetch(url('api/prompts'))).json();
  },
  async createSession(language, optimize, report, participants, diarize) {
    const r = await fetch(url('api/sessions'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language, optimize, report, participants, diarize }),
    });
    if (!r.ok) throw new Error('Kon sessie niet aanmaken');
    return r.json();
  },
  async uploadChunk(sessionId, blob, mime, filename, attempts = 3) {
    const headers = { 'Content-Type': mime || 'application/octet-stream' };
    if (filename) headers['X-Filename'] = filename;
    let lastErr;
    for (let i = 0; i < attempts; i++) {
      try {
        const r = await fetch(url(`api/sessions/${sessionId}/audio`), { method: 'PUT', headers, body: blob });
        if (r.ok) return r.json();
        // 4xx (behalve 408/429) is definitief -> niet opnieuw proberen (bv. 413 te groot, 409 afgerond).
        if (r.status < 500 && r.status !== 408 && r.status !== 429) {
          throw Object.assign(new Error('Chunk-upload geweigerd (' + r.status + ')'), { fatal: true });
        }
        lastErr = new Error('Chunk-upload mislukt (' + r.status + ')');
      } catch (e) {
        if (e.fatal) throw e;      // definitieve fout
        lastErr = e;               // netwerk-/tijdelijke fout -> opnieuw proberen
      }
      if (i < attempts - 1) await new Promise((res) => setTimeout(res, 600 * (i + 1)));
    }
    throw lastErr;
  },
  // Robuuste bestandsupload: hakt het bestand in kleine chunks (past onder proxy-bodylimieten)
  // en hergebruikt de chunked PUT + complete-flow, i.p.v. één grote multipart-POST.
  async uploadFileChunked(file, language, optimize, report, onProgress, participants, diarize) {
    const sess = await this.createSession(language, optimize, report, participants, diarize);
    const id = sess.id;
    const CHUNK = 4 * 1024 * 1024;   // 4 MB
    const mime = file.type || 'application/octet-stream';
    let sent = 0;
    for (let start = 0; start < file.size; start += CHUNK) {
      const blob = file.slice(start, Math.min(start + CHUNK, file.size));
      await this.uploadChunk(id, blob, mime, start === 0 ? file.name : null);
      sent += blob.size;
      if (onProgress) onProgress(sent / (file.size || 1));
    }
    await this.complete(id);
    return { id };
  },
  // Stateless: lees een geüpload tekst-/documentbestand (.docx e.d.) naar platte tekst.
  async extractText(file) {
    const form = new FormData();
    form.append('file', file);
    const r = await fetch(url('api/extract-text'), { method: 'POST', body: form });
    if (!r.ok) throw new Error('Kon het bestand niet lezen (' + r.status + ')');
    return (await r.json()).text || '';
  },
  // Tekst als bron (aantekeningen of bestaand transcript) -> sessie zonder audio/STT, met verslag.
  async createTextSession(file, text, language, report, sourceKind) {
    const form = new FormData();
    if (file) form.append('file', file);
    if (text) form.append('text', text);
    if (language) form.append('language', language);
    if (report) form.append('report', JSON.stringify(report));
    form.append('source_kind', sourceKind || 'notes');
    const r = await fetch(url('api/sessions/text'), { method: 'POST', body: form });
    if (!r.ok) throw new Error('Kon de tekst niet verwerken (' + r.status + ')');
    return r.json();
  },
  async complete(sessionId) {
    const r = await fetch(url(`api/sessions/${sessionId}/complete`), { method: 'POST' });
    if (!r.ok) throw new Error('Afronden mislukt');
    return r.json();
  },
  async deleteSession(sessionId) {
    try { await fetch(url(`api/sessions/${sessionId}`), { method: 'DELETE' }); } catch {}
  },
  async uploadFile(file, language, optimize, report, onProgress) {
    // XHR voor uploadvoortgang.
    return new Promise((resolve, reject) => {
      const form = new FormData();
      form.append('file', file);
      const q = new URLSearchParams();
      if (language) q.set('language', language);
      if (optimize !== undefined) q.set('optimize', optimize ? 'true' : 'false');
      if (report) q.set('report', JSON.stringify(report));
      const endpoint = url('api/upload') + (q.toString() ? `?${q}` : '');
      const xhr = new XMLHttpRequest();
      xhr.open('POST', endpoint);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
        else reject(new Error('Upload mislukt: ' + xhr.status + ' ' + xhr.responseText));
      };
      xhr.onerror = () => reject(new Error('Netwerkfout bij uploaden'));
      xhr.send(form);
    });
  },
  async feedback(sessionId, stars, target) {
    try {
      await fetch(url(`api/sessions/${sessionId}/feedback`), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stars, target }),
      });
    } catch {}
  },
  async wait() {
    try { return await (await fetch(url('api/wait'))).json(); } catch { return null; }
  },
  async status(sessionId) {
    const r = await fetch(url(`api/sessions/${sessionId}/status`));
    if (!r.ok) throw new Error('not-found');
    return r.json();
  },
  async result(sessionId) {
    const r = await fetch(url(`api/sessions/${sessionId}`));
    if (!r.ok) throw new Error('not-found');
    return r.json();
  },
  async createReport(sessionId, payload) {
    const r = await fetch(url(`api/sessions/${sessionId}/reports`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error('Kon verslag niet starten (' + r.status + ')');
    return r.json();
  },
  async getReport(sessionId, reportId) {
    const r = await fetch(url(`api/sessions/${sessionId}/reports/${reportId}`));
    if (!r.ok) throw new Error('not-found');
    return r.json();
  },
  async updateReport(sessionId, reportId, content) {
    const r = await fetch(url(`api/sessions/${sessionId}/reports/${reportId}`), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    if (!r.ok) throw new Error('Opslaan mislukt (' + r.status + ')');
    return r.json();
  },
  async deleteReport(sessionId, reportId) {
    const r = await fetch(url(`api/sessions/${sessionId}/reports/${reportId}`), { method: 'DELETE' });
    if (!r.ok && r.status !== 404) throw new Error('Verwijderen mislukt (' + r.status + ')');
  },
  async rediarize(sessionId, participants) {
    const r = await fetch(url(`api/sessions/${sessionId}/rediarize`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participants }),
    });
    if (!r.ok) throw new Error('Opnieuw indelen mislukt (' + r.status + ')');
    return r.json();
  },
  // Markdown -> docx (stateless), voor client-side export met ingevulde sprekernamen.
  async convertDocx(content) {
    const r = await fetch(url('api/convert/docx'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    if (!r.ok) throw new Error('Word-conversie mislukt (' + r.status + ')');
    return r.blob();
  },
};
