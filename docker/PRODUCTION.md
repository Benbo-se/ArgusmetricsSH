# Produktion på egen server (CI/CD)

Dev sker på arbetsdatorn, prod på servern. Flödet är braleads/hushroom-mönstret,
SSH-varianten (repot är publikt → ingen self-hosted runner på servern):

```
push/PR → CI (smoke mot TimescaleDB + hygien)
  └─ grön main → bygg + pusha images till GHCR
        ghcr.io/benbo-se/argusmetrics-backend:{latest, <sha>}
        ghcr.io/benbo-se/argusmetrics-web:{latest, <sha>}     (nginx + site/)
      └─ Deploy (dispatch, eller auto om DEPLOY_ENABLED=true):
         DB-dump → git pull → pull images → compose up → health → auto-rollback
         → PROD-YYYY-MM-DD-tagg på deployad commit
```

Marknadssiten serveras inte längre via GitHub Pages — web-imagen (nginx) serverar
`site/` på `/` och proxyar app-rutterna (`/api/`, `/login`, `/dashboard`, `/ws/` …)
till backend-containern. En deploy släpper alltså sajt + app atomiskt ihop.

## Engångssetup på servern

1. **Klona + konfigurera**
   ```bash
   sudo git clone https://github.com/Benbo-se/ArgusmetricsSH.git /opt/argusmetrics
   cd /opt/argusmetrics
   cp docker/.env.example docker/.env   # fyll i POSTGRES_PASSWORD, SECRET_KEY,
                                        # ALLOWED_ORIGINS=https://argusmetrics.io
                                        # ev. WEB_PORT (default 8021)
   ```
2. **GHCR-pull**: gör paketen `argusmetrics-backend` och `argusmetrics-web`
   publika under Benbo-se (repot är ändå AGPL) — då krävs ingen `docker login`
   på servern. Annars: `docker login ghcr.io` med en PAT (read:packages).
3. **Första start**: `docker compose -f docker/docker-compose.prod.yml up -d`
   och verifiera `curl -s http://127.0.0.1:8021/health`.
4. **Värd-nginx**: vhost för `argusmetrics.io` som terminerar TLS (certbot) och
   proxyar till `http://127.0.0.1:8021` med `X-Forwarded-Proto https` och
   websocket-upgrade för `/ws/`.
5. **DNS-cutover**: peka `argusmetrics.io` från GitHub Pages till serverns IP,
   och stäng av Pages under repo-settings (annars ligger gamla siten kvar).

   Idag (Loopia): apex A → 185.199.108-111.153 (Pages), `www` CNAME →
   benbo-se.github.io. Byt till: apex A → serverns IP, `www` → samma.

   Vid flytt till **Cloudflare** (proxied/orange moln):
   - SSL/TLS-läge **Full (strict)**; cert på servern via certbot eller ett
     Cloudflare Origin Certificate i värd-nginx.
   - Riktiga besökar-IPs: värd-nginx behöver `set_real_ip_from` för
     Cloudflares IP-ranges + `real_ip_header CF-Connecting-IP`, och backendens
     `TRUSTED_PROXIES` ska omfatta proxykedjan — annars loggar analyticsen
     Cloudflares IPs istället för besökarnas.
   - Websockets (`/ws/`) fungerar genom Cloudflare utan extra konfiguration.

## GitHub-konfiguration

- Secrets: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` (nyckel vars publika
  halva ligger i serverns `authorized_keys`).
- Environment `production`: lägg gärna en required reviewer → klick-godkänd deploy.
- Repo-variabel `DEPLOY_ENABLED=true` när du vill ha helautomatisk deploy på
  grön main; tills dess är grinden manuell "Run workflow".

## Rollback

Varje deploy taggas `PROD-YYYY-MM-DD[-N]` och images taggas med git-SHA.
Manuell rollback: Actions → Deploy → Run workflow → ange förra SHA:n som tag.
Deployen gör dessutom auto-rollback själv om health-checken failar, och en
pre-deploy-dump ligger i `~/backups/argusmetrics/pre-deploy/` på servern.

## Schemaändringar

Backend kör `create_all` vid start (additiva ändringar sker automatiskt).
Versionerade migrationer finns via Alembic:
`docker compose -f docker/docker-compose.prod.yml exec backend alembic upgrade head`.
