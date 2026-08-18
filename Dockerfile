FROM node:22-alpine AS css-builder

WORKDIR /build

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile

COPY src/opswatch/api/templates ./src/opswatch/api/templates
COPY src/opswatch/api/static/input.css ./src/opswatch/api/static/input.css
COPY src/opswatch/api/static/app.js ./src/opswatch/api/static/app.js
RUN pnpm run css:build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY --from=css-builder /build/src/opswatch/api/static/styles.css ./src/opswatch/api/static/styles.css
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install -e . \
    && useradd --system --create-home --home-dir /home/opswatch --shell /usr/sbin/nologin opswatch \
    && chown -R opswatch:opswatch /app

EXPOSE 8000

USER opswatch

CMD ["uvicorn", "opswatch.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
