// Compacte, veilige Markdown -> HTML renderer (geen externe libs).
// Escapet altijd eerst HTML, zodat er geen ruwe HTML uit het transcript/LLM
// wordt geïnjecteerd. Ondersteunt: koppen, vet/cursief/code, links (http[s]),
// opsommingen, genummerde lijsten, tabellen, horizontale lijnen, paragrafen.

function esc(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function inline(s) {
  s = esc(s);
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  s = s.replace(/(^|[^_])_([^_\n]+)_/g, '$1<em>$2</em>');
  // alleen http(s)-links toestaan (veilig)
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return s;
}

function splitRow(line) {
  return line.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map((c) => c.trim());
}

export function renderMarkdown(md) {
  const lines = (md || '').replace(/\r\n/g, '\n').split('\n');
  let html = '';
  let i = 0;
  const isList = (l) => /^\s*[-*]\s+/.test(l);
  const isOrdered = (l) => /^\s*\d+\.\s+/.test(l);
  const isHeading = (l) => /^#{1,6}\s/.test(l);

  while (i < lines.length) {
    const line = lines[i];

    if (isHeading(line)) {
      const m = line.match(/^(#{1,6})\s+(.*)$/);
      const lvl = Math.min(m[1].length, 6);
      html += `<h${lvl}>${inline(m[2])}</h${lvl}>`;
      i++; continue;
    }
    if (/^\s*([-*_]){3,}\s*$/.test(line)) { html += '<hr>'; i++; continue; }

    // Tabel: huidige regel bevat |, volgende regel is de scheidingsregel (---)
    if (line.includes('|') && i + 1 < lines.length &&
        /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(lines[i + 1])) {
      const header = splitRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) {
        rows.push(splitRow(lines[i])); i++;
      }
      html += '<table><thead><tr>' + header.map((c) => `<th>${inline(c)}</th>`).join('') +
        '</tr></thead><tbody>' +
        rows.map((r) => '<tr>' + r.map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>').join('') +
        '</tbody></table>';
      continue;
    }

    if (isList(line)) {
      html += '<ul>';
      while (i < lines.length && isList(lines[i])) {
        html += `<li>${inline(lines[i].replace(/^\s*[-*]\s+/, ''))}</li>`; i++;
      }
      html += '</ul>'; continue;
    }
    if (isOrdered(line)) {
      html += '<ol>';
      while (i < lines.length && isOrdered(lines[i])) {
        html += `<li>${inline(lines[i].replace(/^\s*\d+\.\s+/, ''))}</li>`; i++;
      }
      html += '</ol>'; continue;
    }
    if (!line.trim()) { i++; continue; }

    // Paragraaf: verzamel tot een lege regel of een ander blok
    const para = [line]; i++;
    while (i < lines.length && lines[i].trim() &&
           !isHeading(lines[i]) && !isList(lines[i]) && !isOrdered(lines[i]) &&
           !lines[i].includes('|')) {
      para.push(lines[i]); i++;
    }
    html += `<p>${inline(para.join(' '))}</p>`;
  }
  return html;
}
