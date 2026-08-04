FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install -e . \
    && useradd --system --create-home --home-dir /home/opswatch --shell /usr/sbin/nologin opswatch \
    && chown -R opswatch:opswatch /app

EXPOSE 8000

USER opswatch

CMD ["uvicorn", "opswatch.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
