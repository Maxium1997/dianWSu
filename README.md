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
