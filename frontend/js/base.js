// Basispad van de app, afgeleid van de locatie van DEZE module (import.meta.url). Daardoor werkt
// de app onder ELK subpad achter een reverse-proxy zonder configuratie of build-stap:
//   .../innovatiepijplijn/js/base.js  -> app-root .../innovatiepijplijn/
//   op de web-root:        /js/base.js -> app-root /
// url('api/config') levert dan telkens het juiste absolute pad. Backward-compatible op de root.
const ROOT = new URL('../', import.meta.url);   // '../' vanaf /js/base.js = de app-root

// Absoluut pad binnen de app voor een (root-relatief) pad zonder leidende slash,
// bv. url('api/sessions/x') of url('js/vendor/tiptap.bundle.js') of url('caddy-root.crt').
export function url(path) {
  return new URL(String(path).replace(/^\/+/, ''), ROOT).toString();
}
