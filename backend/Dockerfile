# Facet API — production/UAT image.
#
# Multi-stage: the builder stage compiles wheels for the packages that need a
# C toolchain (psycopg, argon2-cffi, scikit-learn's deps), so the runtime
# image never carries gcc/build-essential — smaller image, smaller attack
# surface.

FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.12-slim AS runtime

# libpq5 for asyncpg/psycopg at runtime; libfreetype6/fontconfig for
# matplotlib and ReportLab's font rendering (PDF exports, coverage charts).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libfreetype6 \
    fontconfig \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 facet
WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .

# Writable at runtime: file-backend email outbox, local file storage (logos),
# matplotlib's font cache. Mount a volume over /app/var in production so this
# survives a container restart instead of resetting.
RUN mkdir -p /app/var/outbox /app/var/storage \
    && chown -R facet:facet /app

USER facet
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLCONFIGDIR=/app/var/.mplcache

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8010/health || exit 1

# Migrations run as a separate one-shot step (see docker-compose), not on
# every container start — running them from inside a scaled-out API replica
# would race with itself.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "2"]
