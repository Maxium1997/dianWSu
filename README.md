# dianWSu

Django Web Application

## Development

```bash
python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

python manage.py migrate
python manage.py runserver
```

## Member login

The member system uses Google and LINE OAuth only. Add the following values to
your local `.env` file before signing in:

```env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
LINE_CHANNEL_ID=
LINE_CHANNEL_SECRET=
```

For local development, register these OAuth redirect URLs with both providers:

```text
http://127.0.0.1:8000/accounts/google/login/callback/
http://127.0.0.1:8000/accounts/line/login/callback/
```

For a deployed site, replace `127.0.0.1:8000` with its HTTPS domain and add
the matching URLs in Google Cloud Console and LINE Developers.

## System logs

Security and account events are stored in Django Admin under **System Logs**.
The records are read-only and include authentication events, third-party account
linking, denied requests, and unhandled application exceptions. Normal page
views are not recorded.

Audit records are retained for 180 days by default. Schedule this command to
run once per day in the deployment environment:

```bash
python manage.py purge_audit_logs
```

Application errors are emitted as JSON to standard output so the deployment
platform can collect and retain them separately. File-integrity monitoring and
alerts for unexpected server files must be configured at the hosting layer.

## Cloudflare production deployment

This is a Django WSGI application. Deploy it to a Python-capable origin (a VPS,
container host, or Kubernetes) and place Cloudflare in front of it. Do not use
Cloudflare Pages as the Django application host. Cloudflare Tunnel is the
recommended origin connection because it does not expose an inbound port or
public origin IP.

### 1. Configure the production environment

Set secrets in the origin platform's secret manager, never in Git:

```env
DJANGO_ENV=production
DEBUG=False
SECRET_KEY=<a-new-long-random-secret>
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME
REQUIRE_POSTGRES=True
ALLOWED_HOSTS=app.example.com
CSRF_TRUSTED_ORIGINS=https://app.example.com
TRUST_CLOUDFLARE_PROXY=True
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=False
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
LINE_CHANNEL_ID=
LINE_CHANNEL_SECRET=
```

Start with `SECURE_HSTS_SECONDS=0` until HTTPS has been verified on the final
domain. Enable the one-year value only after that check succeeds. Set
`SECURE_HSTS_PRELOAD=True` only if every present and future subdomain is HTTPS
ready and you intentionally plan to submit the domain to the preload list.

### 2. Build and release the origin

The included `Dockerfile` runs Gunicorn. During each release, run these commands
once against the production environment before starting new application workers:

```bash
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py configure_site --domain app.example.com
python manage.py check --deploy
```

### Mac mini with Docker Compose

For a personal Mac mini origin, use the included `compose.yaml`. It has no
published ports: the web service, PostgreSQL, scheduler, and Cloudflare Tunnel
communicate only on a private Docker network. Do not add host mounts or Docker
socket mounts to the services. The scheduler removes audit logs older than the
configured 180-day retention window once a day.

1. Install and open Docker Desktop. Confirm it is running with `docker version`.
   If zsh cannot find the command, run this once in that terminal:

   ```bash
   export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
   ```
2. In Cloudflare Dashboard, go to **Networking > Tunnels**, create a remotely
   managed tunnel, and copy its token. This setup does not require installing
   `cloudflared` on macOS.
3. Copy `.env.example` to `.env`, then set the production values below. The
   `DATABASE_URL` password must match `POSTGRES_PASSWORD`:

   ```env
   DJANGO_ENV=production
   DEBUG=False
   SECRET_KEY=<a-new-long-random-secret>
   DATABASE_URL=postgresql://dianwsu:CHANGE_ME@db:5432/dianwsu
   REQUIRE_POSTGRES=True
   POSTGRES_DB=dianwsu
   POSTGRES_USER=dianwsu
   POSTGRES_PASSWORD=CHANGE_ME
   ALLOWED_HOSTS=dotwebsite.cc
   HEALTHCHECK_HOST=dotwebsite.cc
   CSRF_TRUSTED_ORIGINS=https://dotwebsite.cc
   TRUST_CLOUDFLARE_PROXY=True
   SECURE_SSL_REDIRECT=True
   SESSION_COOKIE_SECURE=True
   CSRF_COOKIE_SECURE=True
   CLOUDFLARE_TUNNEL_TOKEN_ACTIVE=<from Cloudflare Dashboard>
   ```

4. Limit the secret file to the current macOS account:

   ```bash
   chmod 600 .env
   ```

5. Build and start PostgreSQL, then run the one-time release commands:

   ```bash
   docker compose config --quiet
   docker compose build web
   docker compose up -d db
   docker compose run --rm web python manage.py migrate --noinput
   docker compose run --rm web python manage.py configure_site --domain dotwebsite.cc
   docker compose run --rm web python manage.py check --deploy
   docker compose up -d
   ```

   Use `docker compose config --quiet`, not plain `docker compose config`:
   the non-quiet command can print values from `.env`.

6. Under the tunnel's public hostname, map `dotwebsite.cc` to
   `http://web:8000`. Cloudflare creates the proxied DNS record automatically.
   Use `dotwebsite.cc` as the sole canonical hostname. If you later enable
   `www`, add it to both Django allow lists and create a Cloudflare Redirect
   Rule from `www.dotwebsite.cc` to `https://dotwebsite.cc`.

   Update the OAuth provider callback settings before testing sign-in:

   ```text
   Google: https://dotwebsite.cc/accounts/google/login/callback/
   LINE:   https://dotwebsite.cc/accounts/line/login/callback/
   ```

7. Confirm the service is healthy:

   ```bash
   docker compose ps
   docker compose logs --tail=100 web cloudflared
   ```

Run a local encrypted PostgreSQL dump with:

```bash
bash scripts/backup_postgres.sh
```

Copy the resulting file in `backups/` to an off-device encrypted destination
such as Cloudflare R2. Do not expose PostgreSQL to the host or public internet.

The health endpoint is available at `/healthz/` and returns JSON without
creating an audit event.

### 3. Configure Cloudflare

1. Add the domain to Cloudflare and create a Cloudflare Tunnel in **Zero Trust
   > Networks > Tunnels**. Run the connector on the origin and map the public
   hostname `app.example.com` to the private Gunicorn service, for example
   `http://127.0.0.1:8000`.
2. Keep the public hostname proxied by Cloudflare. Enforce HTTPS at the edge.
   With Tunnel, the origin service can remain private HTTP because the tunnel is
   outbound and encrypted.
3. Under **Security > WAF**, enable Managed Rules. Add rate limiting or Managed
   Challenge rules for `/accounts/*` and `/admin/*`; do not challenge OAuth
   callback requests so aggressively that a normal provider redirect is blocked.
4. Under **Caching > Cache Rules**, bypass cache for `/admin/*`, `/accounts/*`,
   `/member/*`, and any request carrying a session cookie. Cache `/static/*`
   normally; `collectstatic` gives those assets content-hashed names.
5. Optionally protect `/admin/*` with Cloudflare Access. Do not apply Access to
   `/accounts/*`, because Google and LINE must reach their callback URLs.
6. In Google Cloud Console and LINE Developers, add these exact HTTPS callbacks:

   ```text
   https://app.example.com/accounts/google/login/callback/
   https://app.example.com/accounts/line/login/callback/
   ```

### Character encoding and fonts

Templates declare UTF-8, Django uses UTF-8 for responses, and the Docker image
sets `PYTHONUTF8=1` with `C.UTF-8`; Chinese text will not become mojibake after
deployment. The Noto Sans TC web font is loaded from Google Fonts. If that CDN
is unavailable, browsers use the system CJK fallback font; the appearance may
change slightly, but text encoding remains correct.
