# Beveiliging

Filosofie: **open en toegankelijk, geen login, geen persoonsgegevens**. Het systeem
draait op een **geïsoleerd VLAN, los van het internet**. Onderstaande maatregelen zijn
de applicatielaag daarbovenop, zodat de tool geen onnodige toegangspoort wordt.

## Toegangsmodel

- Geen accounts. De **sessie-code is een capability-token**: 256 bits entropie
  (`secrets.token_urlsafe(32)`, zie `backend/app/tokens.py`). Wie de code niet heeft, kan
  de data niet benaderen; de code is niet te raden of te enumereren.
- Data verloopt automatisch (bewaartermijn in werkdagen) en wordt hard verwijderd
  (`storage.delete_session_files`).

## Maatregelen in de applicatie

| Risico | Maatregel | Waar |
|---|---|---|
| Cross-site scripting (XSS) via transcript/verslag | Markdown-renderer escapet altijd eerst HTML; alleen `http(s)`-links; geen ruwe HTML | `frontend/js/md.js` |
| XSS / injectie algemeen | Strak **Content-Security-Policy** (`script-src 'self'`, geen inline scripts), plus `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, COOP | `Caddyfile` |
| Command-injectie via audio | ffmpeg wordt met een **argumentenlijst** aangeroepen (geen shell) | `backend/worker/audio.py` |
| Path traversal via id's | Sessie/verslag-id's zijn server-gegenereerde tokens; endpoints valideren tegen de DB (404) vóór bestandsoperaties; padparameters matchen geen `/` | `routes.py`, `storage.py` |
| Disk-DoS via upload | Harde uploadlimiet (`MAX_UPLOAD_MB`) afgedwongen bij zowel chunked als single-shot upload; Caddy `request_body max_size` | `routes.py`, `Caddyfile` |
| Info-disclosure | Swagger-UI/OpenAPI **standaard uit** (`EXPOSE_API_DOCS=false`); `Server`-header verwijderd; foutmeldingen bevatten geen interne details/transcript | `main.py`, `Caddyfile` |
| SSRF | LLM-/STT-endpoints staan vast in env (niet door de gebruiker te sturen) | `config.py` |
| Cross-origin misbruik | Geen CORS-header → alleen same-origin; geen cookies/sessies | `main.py` |

## Zelf testen

Vervang `HOST` door je site (bv. `beestjeai2`). `-k` omdat de interne CA mogelijk niet
door curl wordt vertrouwd.

```bash
# 1) Security-headers aanwezig (CSP, X-Frame-Options, geen Server-header)?
curl -skI https://HOST/ | grep -iE "content-security-policy|x-frame|x-content-type|referrer-policy|permissions-policy|^server"

# 2) API-docs dicht in productie? (verwacht 404)
curl -sk -o /dev/null -w "%{http_code}\n" https://HOST/api/openapi.json
curl -sk -o /dev/null -w "%{http_code}\n" https://HOST/api/docs

# 3) Onbekende/geraden sessie-code geeft 404 (geen enumeratie)?
curl -sk -o /dev/null -w "%{http_code}\n" https://HOST/api/sessions/onzin-bestaat-niet

# 4) Uploadlimiet leeft (verwacht 413 bij overschrijding MAX_UPLOAD_MB).
#    (functioneel te testen via een groot bestand op /api/upload)
```

Voor een diepere codegerichte review: draai `/security-review` op de branch.

## Bewust (nog) niet — zie ROADMAP.md

Rate-limiting, ffmpeg-sandboxing en rand-WAF/fail2ban staan op de roadmap; nu achterwege
gelaten omdat het systeem op een geïsoleerd VLAN draait. Toevoegen zodra bredere toegang
in beeld komt.
