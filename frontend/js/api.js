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
  async uploadChunk(sessionId, blob, mime, filename) {
    const headers = { 'Content-Type': mime || 'application/octet-stream' };
    if (filename) headers['X-Filename'] = filename;
    const r = await fetch(`/api/sessions/${sessionId}/audio`, {
      method: 'PUT',
      headers,
      body: blob,
    });
    if (!r.ok) throw new Error('Chunk-upload mislukt (' + r.status + ')');
    return r.json();
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
};
