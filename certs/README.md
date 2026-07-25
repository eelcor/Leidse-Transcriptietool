# Eigen TLS-certificaat

Leg hier je certificaat en sleutel neer om de browserwaarschuwing te voorkomen:

- `cert.pem` — je certificaat (fullchain: server + eventuele intermediates)
- `key.pem`  — de bijbehorende private sleutel

Zet in `.env`:

```
CADDY_TLS=/certs/cert.pem /certs/key.pem
```

Gebruik een certificaat dat je clients al vertrouwen: één van je interne CA (via
AD/GPO uitgerold) of een publiek certificaat voor een echt domein. Dan is er geen
waarschuwing en hoef je op de clients niets te installeren.

De echte `.pem`-bestanden worden NIET in git bewaard (zie .gitignore).
