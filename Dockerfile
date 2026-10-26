# syntax=docker/dockerfile:1
# Multi-arch (amd64 + arm64): docker buildx build --platform linux/amd64,linux/arm64 .

FROM --platform=$BUILDPLATFORM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN groupadd --system --gid 10001 camdash \
    && useradd --system --uid 10001 --gid camdash --home-dir /app --shell /usr/sbin/nologin camdash \
    && mkdir -p /data && chown camdash:camdash /data
WORKDIR /app
COPY backend/pyproject.toml ./
# Install only the runtime dependencies; the app itself runs from /app so alembic files resolve.
RUN python -c "import tomllib; open('/tmp/req.txt','w').write('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" \
    && pip install -r /tmp/req.txt && rm /tmp/req.txt
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY --from=frontend /src/dist ./static
USER camdash
EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"]
CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
