# OpsWatch

OpsWatch is a local-first uptime monitoring and incident response MVP.

It lets an admin create HTTP monitors, run checks, record check results, and track incidents from a small dashboard.

Current version: `0.3.1`

## What It Does

- creates HTTP monitors
- edits monitors from the dashboard
- pauses and resumes monitors from the dashboard
- runs scheduled checks in a worker process
- supports manual checks from the dashboard and JSON API
- records status code, latency, and error details
- stores current monitor state on each monitor
- opens an incident after repeated failures
- resolves an open incident after enough successful checks
- shows monitors, checks, and incidents in a dark Tailwind dashboard

## Architecture

```text
Browser
  -> Nginx
  -> FastAPI dashboard routes
  -> Jinja templates
  -> HTML response

JSON clients
  -> Nginx
  -> FastAPI API routes
  -> JSON response

FastAPI and worker
  -> SQLAlchemy
  -> PgBouncer
  -> PostgreSQL

Worker
  -> httpx
  -> monitored URLs
```

## Data Model

```text
Monitor
  stores configuration and current state

MonitorCheck
  stores check history

Incident
  stores a period where a monitor is failing or needs attention
```

Monitor state values:

```text
unknown   no check has confirmed the current state
healthy   the monitor is passing checks
degraded  the monitor has failures but is not confirmed down, or is recovering
down      the monitor reached its failure threshold
paused    the monitor is disabled
```

Threshold fields:

```text
failure_threshold   failed checks needed to mark a monitor down
recovery_threshold  successful checks needed to resolve an incident
```

## Services

The Docker Compose stack runs:

- `nginx`: public entry point on port `80`
- `api`: FastAPI dashboard and JSON API
- `worker`: background process that runs due monitor checks
- `postgres`: PostgreSQL database
- `pgbouncer`: database connection pooler
- `failure-lab`: local test service with healthy, failing, slow, and toggle routes

## Container Runtime

The Python containers are built to be closer to a production runtime:

- the app runs as a non-root `opswatch` user
- API, worker, failure lab, Nginx, PgBouncer, and PostgreSQL have healthchecks
- worker startup waits for the API to become healthy
- Nginx waits for the API and failure lab to become healthy
- API, worker, and failure lab use a read-only container filesystem
- API, worker, and failure lab drop Linux capabilities
- API, worker, and failure lab use `no-new-privileges`
- services restart with `unless-stopped`

## Dashboard Routes

These routes render HTML with Jinja:

```text
GET  /
GET  /login
POST /login
POST /logout
GET  /monitors
POST /monitors
GET  /monitors/{monitor_id}
POST /monitors/{monitor_id}
POST /monitors/{monitor_id}/check
POST /monitors/{monitor_id}/delete
GET  /incidents
GET  /incidents/{incident_id}
POST /incidents/{incident_id}
```

## JSON API Routes

These routes return JSON:

```text
GET    /api/v1/monitors
POST   /api/v1/monitors
GET    /api/v1/monitors/{monitor_id}
PATCH  /api/v1/monitors/{monitor_id}
DELETE /api/v1/monitors/{monitor_id}
POST   /api/v1/monitors/{monitor_id}/check
GET    /api/v1/monitors/{monitor_id}/checks
GET    /api/v1/checks
GET    /api/v1/incidents
GET    /api/v1/incidents/{incident_id}
PATCH  /api/v1/incidents/{incident_id}
```

## Health Routes

```text
GET /health
GET /ready
GET /version
```

- `/health` confirms the FastAPI process is running.
- `/ready` confirms the app can query the database.
- `/version` returns the app version and git commit value.

## Local Login

Default local dashboard credentials:

- username: `admin`
- password: `admin`

These credentials are for local development only and must be changed before any public deployment.

## Quick Start

On this machine, use `docker-compose`:

```powershell
cd C:\Users\asus\Desktop\Projects\OpsWatch\OpsWatch
docker-compose up --build
```

Then open:

- Dashboard: http://localhost
- API health: http://localhost/health
- Failure Lab: http://localhost/failure-lab/health

If the database volume has old local data that you do not need:

```powershell
docker-compose down -v
docker-compose up --build
```

## Useful Demo Monitors

When running through Docker Compose, use these URLs inside OpsWatch:

```text
http://failure-lab:9000/health
http://failure-lab:9000/fail
http://failure-lab:9000/wrong-body
http://failure-lab:9000/slow?seconds=8
http://failure-lab:9000/toggle
```

Use `http://failure-lab:9000/...` because the API and worker run inside Docker. They should not use `localhost` to reach the failure lab.

## Useful Commands

```powershell
docker-compose ps
docker-compose logs -f api
docker-compose logs -f worker
docker-compose logs -f nginx
docker-compose down
```

## Development Tests

Install development dependencies, then run tests:

```bash
pip install -e ".[dev]"
pytest
```

## UI

The dashboard uses Jinja templates with Tailwind loaded from the CDN.

This keeps the current app simple because there is no Node build step yet. A later production pass should replace the CDN with a compiled Tailwind CSS file.

## Naming Rules

Code should use plain names that match the product:

- `Monitor`: something OpsWatch checks
- `MonitorCheck`: one saved check result
- `Incident`: a period where a monitor is failing or needs attention
- `check_monitor_endpoint`: sends one HTTP request for a monitor
- `record_monitor_check_result`: saves the result and updates incidents
- `recovery_threshold`: successful checks needed to recover

Docstrings should be short, direct, and accurate.
