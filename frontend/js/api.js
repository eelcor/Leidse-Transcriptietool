// Dunne API-client. Alle calls gaan naar /api (Caddy proxyt naar de FastAPI-service).
export const API = {
  async config() {
    return (await fetch('/api/config')).json();
  },
  async prompts() {
    return (await fetch('/api/prompts')).json();
  },
  async createSession(language, optimize, report) {
    const r = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language, optimize, report }),
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
        const r = await fetch(`/api/sessions/${sessionId}/audio`, { method: 'PUT', headers, body: blob });
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
  async uploadFileChunked(file, language, optimize, report, onProgress) {
    const sess = await this.createSession(language, optimize, report);
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
  async complete(sessionId) {
    const r = await fetch(`/api/sessions/${sessionId}/complete`, { method: 'POST' });
    if (!r.ok) throw new Error('Afronden mislukt');
    return r.json();
  },
  async deleteSession(sessionId) {
    try { await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' }); } catch {}
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
      const url = '/api/upload' + (q.toString() ? `?${q}` : '');
      const xhr = new XMLHttpRequest();
      xhr.open('POST', url);
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
      await fetch(`/api/sessions/${sessionId}/feedback`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stars, target }),
      });
    } catch {}
  },
  async wait() {
    try { return await (await fetch('/api/wait')).json(); } catch { return null; }
  },
  async status(sessionId) {
    const r = await fetch(`/api/sessions/${sessionId}/status`);
    if (!r.ok) throw new Error('not-found');
    return r.json();
  },
  async result(sessionId) {
    const r = await fetch(`/api/sessions/${sessionId}`);
    if (!r.ok) throw new Error('not-found');
    return r.json();
  },
  async createReport(sessionId, payload) {
    const r = await fetch(`/api/sessions/${sessionId}/reports`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error('Kon verslag niet starten (' + r.status + ')');
    return r.json();
  },
  async getReport(sessionId, reportId) {
    const r = await fetch(`/api/sessions/${sessionId}/reports/${reportId}`);
    if (!r.ok) throw new Error('not-found');
    return r.json();
  },
  async updateReport(sessionId, reportId, content) {
    const r = await fetch(`/api/sessions/${sessionId}/reports/${reportId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    if (!r.ok) throw new Error('Opslaan mislukt (' + r.status + ')');
    return r.json();
  },
};
