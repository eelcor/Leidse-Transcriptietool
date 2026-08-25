# Woordenlijsten (glossary's) — plugin-map

Elk bestand in deze map is **één woordenlijst** die in de app verschijnt in het keuzemenu
onder *Verslag → Woordenlijst / jargon*. De gekozen lijst stuurt zowel de **transcriptie**
(betere herkenning) als het **verslag** (juiste spelling van namen/vaktermen/afkortingen).

## Zelf een lijst toevoegen
Zet een `.txt`- of `.md`-bestand in deze map. **Geen herstart nodig** — de app leest de map
live in via `GET /api/glossaries` (bij het openen van het startscherm).

Elke gemeente/organisatie kan zo een **eigen** lijst gebruiken: de map is een read-only
bind-mount (`./glossaries` → `/glossaries`), dus je kunt 'm ook naar een eigen map laten wijzen
via `GLOSSARY_DIR` in `.env` zonder de repo te wijzigen.

## Formaat
- **Eén term (of korte frase) per regel.**
- Regels die met `#` beginnen zijn **commentaar** (secties, uitleg) en worden genegeerd.
- De **naam** in het menu komt uit de bestandsnaam (leidend volgnummer als `10-` valt weg,
  streepjes worden spaties), of expliciet via een eerste regel `# naam: Mijn lijst`.
- Bestanden die met `_` of `.` beginnen (zoals deze README) worden overgeslagen.
- Een leidend volgnummer (`10-`, `20-`) bepaalt de **volgorde** in het menu.
- **Altijd meenemen:** een bestandsnaam die met `00` begint (of een regel `# altijd` in het
  bestand) markeert een **basislijst** (bijv. algemene eigennamen). Die wordt **automatisch
  gecombineerd** met de gekozen domeinlijst, zodat je altijd de kernnamen erbij hebt.

## Voorbeeld
```
# naam: Ruimtelijk en omgeving
# Omgevingswet
Omgevingsvisie
omgevingsplan
BOPA
# Projecten
Leidse Ring Noord
```

> De meegeleverde lijsten zijn **startpunten** op basis van gangbaar gemeentelijk jargon.
> Vervang/vul ze aan met de termen uit jullie eigen beleid (bv. uit de beleidswiki):
> juist gespelde eigennamen, projectnamen en afkortingen leveren de grootste winst op.
