// Statistiek-dashboard: haalt /api/stats op en rendert tiles + eenvoudige grafieken.
import { url } from './base.js';

const $ = (s) => document.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k === 'html') n.innerHTML = v;
    else n.setAttribute(k, v);
  }
  for (const kid of kids) n.append(kid?.nodeType ? kid : document.createTextNode(kid ?? ''));
  return n;
};

function tile(label, value, sub, cls) {
  return el('div', { class: 'tile' + (cls ? ' ' + cls : '') },
    el('div', { class: 'v' }, value == null ? '—' : String(value)),
    el('div', { class: 'l' }, label),
    sub ? el('div', { class: 's' }, sub) : document.createTextNode(''),
  );
}

function vbars(container, values, labelFn) {
  const c = $(container); c.innerHTML = '';
  const max = Math.max(1, ...values);
  const wrap = el('div', { class: 'vbars' });
  values.forEach((v, i) => {
    const col = el('div', { class: 'col' });
    const bar = el('div', { class: 'bar', title: v });
    bar.style.height = `${Math.round((v / max) * 100)}%`;
    col.append(bar);
    const lbl = labelFn ? labelFn(i) : '';
    col.append(el('div', { class: 'cl' }, lbl));
    wrap.append(col);
  });
  c.append(wrap);
}

function hbars(container, dict, opts = {}) {
  const c = $(container); c.innerHTML = '';
  const entries = Object.entries(dict || {});
  if (!entries.length) { c.append(el('div', { class: 'empty' }, opts.empty || 'Nog geen data.')); return; }
  const total = entries.reduce((a, [, v]) => a + v, 0) || 1;
  const wrap = el('div', { class: 'hbars' });
  entries.forEach(([k, v]) => {
    const row = el('div', { class: 'hbar' });
    row.append(el('div', { class: 'k' }, opts.label ? opts.label(k) : k));
    const track = el('div', { class: 'track' });
    const fill = el('div', { class: 'fill' }); fill.style.width = `${Math.round((v / total) * 100)}%`;
    track.append(fill); row.append(track);
    row.append(el('div', { class: 'n' }, opts.pct ? `${Math.round((v / total) * 100)}%` : String(v)));
    wrap.append(row);
  });
  c.append(wrap);
}

function fmtDur(s) { return s == null ? '—' : (s >= 60 ? `${(s / 60).toFixed(1)} min` : `${s.toFixed(1)}s`); }

async function main() {
  let d;
  try { d = await (await fetch(url('api/stats'))).json(); }
  catch { $('#totals').append(el('div', { class: 'empty' }, 'Statistieken niet beschikbaar.')); return; }

  // Live
  const live = d.live || {};
  const eta = live.eta_seconds ? (live.eta_seconds >= 60 ? `~${Math.round(live.eta_seconds / 60)} min` : `~${live.eta_seconds}s`) : 'geen wachttijd';
  $('#live').replaceChildren(
    tile('Geschatte wachttijd', eta, `gem. ${fmtDur(live.avg_transcribe_seconds)}/transcriptie`, 'live'),
    tile('In de wachtrij', live.queued ?? 0, null, 'live'),
    tile('Nu in verwerking', live.in_progress ?? 0, null, 'live'),
  );

  // Totalen
  const t = d.totals || {};
  const sat = d.satisfaction || {};
  $('#totals').replaceChildren(
    tile('Transcripties', t.transcriptions ?? 0),
    tile('Audio-uren', t.audio_hours ?? 0, `gem. ${fmtDur(t.avg_audio_seconds)}/gesprek`),
    tile('Woorden', (t.words ?? 0).toLocaleString('nl-NL')),
    tile('Verslagen', t.reports ?? 0),
    tile('Succespercentage', t.success_rate == null ? '—' : `${t.success_rate}%`),
    tile('Tevredenheid', sat.avg == null ? '—' : `${sat.avg} ★`, `${sat.count || 0} beoordelingen`),
  );

  // Wanneer
  vbars('#by-hour', d.by_hour || [], (i) => (i % 3 === 0 ? String(i) : ''));
  const wd = ['ma', 'di', 'wo', 'do', 'vr', 'za', 'zo'];
  vbars('#by-weekday', d.by_weekday || [], (i) => wd[i]);
  const trend = d.trend || [];
  vbars('#trend', trend.map((x) => x.count), (i) => {
    if (i % 5 === 0 && trend[i]) { const p = trend[i].date.split('-'); return `${p[2]}/${p[1]}`; }
    return '';
  });

  // Gebruik
  hbars('#source', d.source, { label: (k) => (k === 'record' ? 'Opname' : 'Upload') });
  hbars('#formats', d.formats);
  hbars('#report-modes', d.report_modes, { label: modeLabel });
  hbars('#languages', d.languages, { label: (k) => k.toUpperCase() });

  // Prestaties
  const pr = d.processing || {};
  const p = (o) => o ? `gem. ${fmtDur(o.avg)} · p50 ${fmtDur(o.p50)} · p90 ${fmtDur(o.p90)}` : '—';
  $('#processing').replaceChildren(
    el('div', { class: 'hbars' },
      el('div', { class: 'hbar', style: 'grid-template-columns:110px 1fr' },
        el('div', { class: 'k' }, 'Transcriptie'), el('div', { class: 'n', style: 'text-align:left;color:var(--text-soft)' }, p(pr.transcribe))),
      el('div', { class: 'hbar', style: 'grid-template-columns:110px 1fr' },
        el('div', { class: 'k' }, 'Verslag'), el('div', { class: 'n', style: 'text-align:left;color:var(--text-soft)' }, p(pr.report))),
    ),
  );

  // Tevredenheid
  const dist = sat.distribution || {};
  $('#satisfaction').replaceChildren(
    el('div', { style: 'font-size:28px;font-weight:800;margin-bottom:10px' },
      sat.avg == null ? 'Nog geen beoordelingen' : `${sat.avg} ★`,
      el('span', { style: 'font-size:13px;font-weight:500;color:var(--muted)' }, sat.avg == null ? '' : `  (${sat.count})`)),
  );
  hbars('#satisfaction', { '5 ★': dist['5'] || 0, '4 ★': dist['4'] || 0, '3 ★': dist['3'] || 0, '2 ★': dist['2'] || 0, '1 ★': dist['1'] || 0 }, { empty: 'Nog geen beoordelingen.' });

  hbars('#downloads', d.downloads, { label: dlLabel, empty: 'Nog geen downloads.' });

  $('#generated').textContent = 'Bijgewerkt: ' + new Date(d.generated_at).toLocaleString('nl-NL');
}

function modeLabel(k) { return { volledig: 'Volledig verslag', secties: 'Losse secties', eigen: 'Eigen prompt', geen: 'Geen verslag' }[k] || k; }
function dlLabel(k) { return { audio: 'Audio', transcript: 'Transcript', report_docx: 'Word', report_md: 'Markdown' }[k] || k; }

main();

// Topbar verbergen bij omlaag scrollen, tonen bij omhoog (autohide).
(function () {
  const bar = document.querySelector('.topbar');
  if (!bar) return;
  let lastY = window.scrollY || 0, ticking = false;
  const update = () => {
    const y = window.scrollY || 0;
    if (y > lastY && y > bar.offsetHeight + 8) bar.classList.add('hide');
    else if (y < lastY) bar.classList.remove('hide');
    lastY = y; ticking = false;
  };
  window.addEventListener('scroll', () => { if (!ticking) { requestAnimationFrame(update); ticking = true; } }, { passive: true });
})();
