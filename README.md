# OpsWatch

OpsWatch is a local-first uptime monitoring and incident response platform.

The V1 demo runs with Docker Compose and shows the core operations loop:

- create HTTP monitors
- run scheduled and manual checks
- record status, latency, and errors
- open incidents after repeated failures
- resolve incidents after recovery
- inspect everything from a small operator dashboard

Default local dashboard credentials:

- username: `admin`
- password: `admin`

These credentials are for local development only and must be changed before any
public deployment.

## Local Stack

```text
Nginx
  -> FastAPI dashboard/API
  -> Failure Lab

FastAPI API
  -> PgBouncer
  -> PostgreSQL

Monitoring worker
  -> PgBouncer
  -> PostgreSQL
  -> monitored URLs
```

## Quick Start

```bash
cp .env.example .env
docker compose up --build
```

Then open:

- Dashboard: http://localhost
- API health: http://localhost/health
- Failure Lab: http://localhost/failure-lab/health

## Useful Demo Monitors

When running through Docker Compose, these URLs are reachable from the API and
worker containers:

- `http://failure-lab:9000/health`
- `http://failure-lab:9000/fail`
- `http://failure-lab:9000/wrong-body`
- `http://failure-lab:9000/slow?seconds=8`
- `http://failure-lab:9000/toggle`

## Tests

```bash
pip install -e ".[dev]"
pytest
```
