# Produktion på egen server (CI/CD)

> **Ingen server är uppsatt än.** Allt nedan är förberett och testat så långt
> det går utan hårdvara: images byggs på grön main, deploy-workflowen finns,
> och återställningsövningen körs i CI vid varje push. Det som återstår är
> engångssetupen i nästa avsnitt. Inget av detta har körts skarpt.

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
                                        # BASE_URL=https://www.argusmetrics.io
                                        # ev. WEB_PORT (default 8021)
   ```
   `BASE_URL` styr backendens TrustedHost-allowlist: bara den hosten släpps
   igenom i prod-läge (`www.`-formen täcker även apex). Låt värd-nginx
   301:a `www` → apex så all trafik är kanonisk.
2. **GHCR-pull**: paketen `argusmetrics-backend` och `argusmetrics-web` är
   privata (orgens paketpolicy tillåter inte publika paket i nuläget), så
   servern behöver en engångsinloggning: skapa en classic PAT med enbart
   `read:packages`-scope och kör `docker login ghcr.io -u <användare>` med
   PAT:en som lösenord (sparas i deploy-användarens `~/.docker/config.json`).
   Görs paketen publika i framtiden kan inloggningen tas bort.
3. **Första start**: `docker compose -f docker/docker-compose.prod.yml up -d`
   och verifiera `curl -s http://127.0.0.1:8021/health`.
4. **Värd-nginx**: vhost för `argusmetrics.io` som terminerar TLS (certbot) och
   proxyar till `http://127.0.0.1:8021` med `X-Forwarded-Proto https` och
   websocket-upgrade för `/ws/`.
5. **DNS-cutover** (ej gjord): peka `argusmetrics.io` från GitHub Pages till serverns IP,
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

## Första kontot

Registreringen är stängd i prod-composen, vilket betyder att en färsk databas
inte har någon väg in: det enda som skapar konton är en inbjudan, och det finns
ingen som kan skicka en. Kör en gång, efter första start:

```bash
docker compose -f docker/docker-compose.prod.yml exec backend \
    python -m app.bootstrap
```

Den frågar efter adress och lösenord. Lösenordet tas aldrig som argument:
argument hamnar i shell-historiken och syns i `ps` för alla på maskinen.

Kontot skapas verifierat, eftersom det inte finns någon inkorg att kontrollera
mot och ingen inbjudan som bevisar adressen. Den som kan köra ett kommando
inuti containern har redan databasen.

Kommandot **vägrar så fort det finns ett konto**. Efter det första bjuder man in
folk från Team-fliken på den webbplats de ska se, vilket är godkännandet och
lämnar ett spår av vem som släppte in vem.

## Backup och återställning

Det här avsnittet är det viktigaste i filen, för det var trasigt.

En vanlig `pg_dump` av en TimescaleDB-databas återställs **tom**. Schemat kommer
tillbaka, sedan avbryts dataladdningen på en konflikt i TimescaleDB:s egen
katalog, och varje tabell har noll rader. Det ser ut som att det gick bra om man
inte räknar. Dumparna togs före varje deploy och ingen hade någonsin återställt
en.

Rätt procedur, som `scripts/verify-backup.sh` gör:

```bash
# Dump
pg_dump --clean --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > backup.sql.gz

# Återställning: klamrarna är inte valfria
psql -U "$POSTGRES_USER" -d "$TARGET" -c \
  'CREATE EXTENSION IF NOT EXISTS timescaledb; SELECT timescaledb_pre_restore();'
gunzip -c backup.sql.gz | psql -U "$POSTGRES_USER" -d "$TARGET" -v ON_ERROR_STOP=1
psql -U "$POSTGRES_USER" -d "$TARGET" -c 'SELECT timescaledb_post_restore();'
```

**Räkna alltid efteråt**, och räkna en hypertabell, inte bara `users`. Felet
som ska fångas är att katalogen avbryter dataladdningen, och det är precis det
som lämnar hypertabellerna tomma medan `users` kommer tillbaka fint:

```sql
SELECT count(*) FROM pageviews;
SELECT count(*) FROM timescaledb_information.chunks;
SELECT count(*) FROM pg_policies;   -- en återställning utan RLS-policyer är oisolerad
```

CI kör hela den här övningen vid varje push, med riktig trafik sådd över två
chunkar, och jämför alla tre siffrorna mot källan.

Kvar att göra när servern finns: schemalägg dumparna, lägg kopior utanför
maskinen, sätt en GPG-mottagare för kryptering, och kör en riktig återställning
en gång för hand. Se issue #2.

## Schemaändringar

Backend-imagens entrypoint kör `alembic upgrade head` före varje start, så
schemat följer alltid koden — en fräsch databas får hela schemat från
baslinje-migrationen, och en databas från tiden före Alembic adopteras
automatiskt (stamp + upgrade). Inga manuella migrationssteg.
