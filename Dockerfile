FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    LANG=C.UTF-8

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
RUN chown -R app:app /app

# Static assets do not require runtime secrets or a live database. Building them
# here keeps the web container read-only and gives Cloudflare cache-safe hashes.
RUN SECRET_KEY=build-only-secret-key-not-used-at-runtime-2026 \
    DJANGO_ENV=production \
    DEBUG=False \
    DATABASE_URL=postgresql://build:build@db:5432/build \
    REQUIRE_POSTGRES=True \
    python manage.py collectstatic --noinput

USER app
EXPOSE 8000

CMD ["gunicorn", "dianWSu.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--worker-tmp-dir", "/tmp", "--access-logfile", "-", "--error-logfile", "-"]
