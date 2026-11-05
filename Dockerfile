FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system blog && adduser --system --ingroup blog blog
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=blog:blog . ./
RUN mkdir -p /app/staticfiles \
    && chown blog:blog /app/staticfiles
USER blog

RUN DJANGO_SECRET_KEY=collectstatic-build-placeholder \
    DJANGO_DEBUG=false \
    DJANGO_ALLOWED_HOSTS=localhost \
    DATABASE_URL=postgresql://build:build@localhost:5432/build \
    STATIC_ROOT=/app/staticfiles \
    python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["sh", "-c", "exec gunicorn blog.wsgi:application --config python:blog.gunicorn_config --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-30} --no-control-socket --error-logfile -"]
