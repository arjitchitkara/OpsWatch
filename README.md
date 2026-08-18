# OpsWatch

OpsWatch is a local-first uptime monitoring and incident response MVP.

It lets an admin create HTTP monitors, run checks, record check results, and track incidents from a small dashboard.

Current version: `0.4.0`

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
- shows monitors, checks, and incidents in a responsive Tailwind and daisyUI dashboard
- filters and paginates monitor and incident lists
- protects dashboard forms with CSRF tokens
- shows clear validation errors and action feedback
- exposes `/metrics` in Prometheus text format
- includes Prometheus and Grafana for local observability
- collects container logs with Grafana Alloy and stores them in Loki

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

Prometheus
  -> FastAPI /metrics
  -> Worker /metrics
  -> time-series storage

Grafana
  -> Prometheus
  -> dashboards

Alloy
  -> Docker container logs
  -> Loki
  -> Grafana logs dashboard
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
- `prometheus`: metrics database that scrapes the OpsWatch `/metrics` route
- `grafana`: dashboard tool that visualizes Prometheus metrics
- `loki`: log database that stores container logs
- `alloy`: log collector that reads Docker container logs and sends them to Loki

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
GET /metrics
```

- `/health` confirms the FastAPI process is running.
- `/ready` confirms the app can query the database.
- `/version` returns the app version and git commit value.
- `/metrics` returns application metrics that Prometheus can scrape.

## Metrics

The `/metrics` route returns plain text in Prometheus format.

Current metrics:

```text
opswatch_monitors_count
opswatch_monitor_status_count{status="healthy|degraded|down|paused|unknown"}
opswatch_monitor_enabled_count{enabled="true|false"}
opswatch_monitor_checks_count
opswatch_monitor_check_result_count{success="true|false"}
opswatch_incidents_count
opswatch_incident_status_count{status="open|acknowledged|resolved"}
opswatch_worker_loop_runs_total
opswatch_worker_loop_failures_total
opswatch_worker_loop_duration_seconds
opswatch_worker_monitor_checks_total{result="success|failure",error_type="none|timeout|request_error|unexpected_status|expected_body_missing"}
opswatch_worker_monitor_check_duration_seconds
opswatch_worker_monitor_check_skipped_total{reason="disabled|not_due"}
```

Open it locally:

```text
http://localhost/metrics
```

Prometheus scrapes this endpoint from inside Docker Compose:

```text
http://api:8000/metrics
http://worker:9100/metrics
```

The Prometheus config lives at:

```text
config/prometheus/prometheus.yml
```

Prometheus is exposed only on this machine:

```text
http://localhost:9090
```

The metrics data is stored in the `prometheus_data` Docker volume. The local retention time is `7d`, so old metrics are removed after seven days.

## Grafana

Grafana reads metrics from Prometheus and turns them into dashboards.

Open Grafana locally:

```text
http://localhost:3000
```

Default local Grafana credentials:

```text
username: admin
password: admin
```

Grafana is provisioned from files in the repo:

```text
config/grafana/provisioning/datasources/prometheus.yml
config/grafana/provisioning/dashboards/opswatch.yml
config/grafana/provisioning/alerting/opswatch-alerts.yml
config/grafana/dashboards/opswatch-overview.json
config/grafana/dashboards/opswatch-worker.json
config/grafana/dashboards/opswatch-logs.json
```

The provisioned datasource points to Prometheus from inside Docker Compose:

```text
http://prometheus:9090
```

Grafana also has a Loki datasource for logs:

```text
http://loki:3100
```

The Grafana app data is stored in the `grafana_data` Docker volume.

The Grafana dashboards are split by purpose:

```text
OpsWatch Overview  product state, monitor state, checks, and incidents
OpsWatch Worker    background worker loops, check results, durations, and skipped checks
OpsWatch Logs      API, worker, and stack logs from Loki
```

Grafana also provisions a local alert rule:

```text
Down monitors detected
API metrics scrape is down
Worker metrics scrape is down
Worker stopped running loops
Worker loop failures detected
Monitor check failures increased
Loki metrics scrape is down
Alloy metrics scrape is down
Alloy is dropping log entries
```

The monitor alert fires when this Prometheus query is greater than zero:

```text
sum(opswatch_monitor_status_count{status="down"}) or vector(0)
```

The platform alerts watch whether Prometheus can scrape the API, worker, Loki, and Alloy. They also watch worker activity and the log pipeline.

No paid email, Slack, or external notification service is required for this alert. It is visible in the Grafana Alerting UI.

## Logs

Application logs are written to container stdout and stderr.

View worker logs:

```powershell
docker-compose logs -f worker
```

Worker logs use one JSON object per event. Example:

```json
{"component":"worker","event":"monitor_check_started","monitor_id":1,"monitor_name":"Demo"}
{"component":"worker","event":"monitor_check_completed","monitor_id":1,"success":true,"status_code":200,"response_time_ms":42,"monitor_status":"healthy"}
```

Important worker events:

```text
worker_started
monitor_check_skipped
monitor_check_started
monitor_check_completed
worker_loop_failed
```

API requests also use structured JSON logs. Example:

```json
{"component":"api","event":"api_request_completed","request_id":"...","method":"GET","path":"/health","status_code":200,"duration_ms":4}
```

Each API response includes an `x-request-id` header. If the request already has an `x-request-id` header, OpsWatch keeps it. Otherwise, OpsWatch creates a new one.

API request logs do not include request bodies or form values. This avoids logging passwords or other sensitive input.

Grafana Alloy collects Docker container logs for OpsWatch services and sends them to Loki.

The Alloy config lives at:

```text
config/alloy/config.alloy
```

The Loki config lives at:

```text
config/loki/loki.yml
```

Loki is exposed only on this machine:

```text
http://localhost:3100
```

Alloy's local debugging UI is exposed only on this machine:

```text
http://localhost:12345
```

The Loki log data is stored in the `loki_data` Docker volume. The Alloy runtime data is stored in the `alloy_data` Docker volume.

Useful Loki queries in Grafana:

```logql
{app="opswatch", service_name=~"api|worker"} | json
{app="opswatch", service_name="api"} | json | event="api_request_completed"
{app="opswatch", service_name="worker"} | json
{app="opswatch"} |~ "(?i)(error|failed|exception|timeout)"
```

## Local Login

Default local dashboard credentials:

- username: `admin`
- password: `admin`

These credentials are for local development only and must be changed before any public deployment.

Default local Grafana credentials are also `admin` / `admin`.

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
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000
- Loki: http://localhost:3100
- Alloy: http://localhost:12345

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
docker-compose logs -f prometheus
docker-compose logs -f grafana
docker-compose logs -f loki
docker-compose logs -f alloy
docker-compose down
```

## Development Tests

Install development dependencies, then run tests:

```bash
pip install -e ".[dev]"
pytest
```

## UI

The product dashboard uses:

- FastAPI dashboard routes
- Jinja templates
- Tailwind CSS 4
- daisyUI components
- a custom dark OpsWatch theme
- a small vanilla JavaScript file for local times, form state, confirmation prompts, and overview refresh

The dashboard remains server-rendered. React is not required for the current forms, tables, filters, and incident workflow.

Tailwind and daisyUI are compiled into:

```text
src/opswatch/api/static/styles.css
```

The dashboard does not load Tailwind from a public CDN. The Dockerfile uses a Node build stage to install the locked frontend dependencies and compile the CSS. The final Python image receives only the generated stylesheet; Node is not a running production service.

Static stylesheet and JavaScript URLs include a file-based version value so browsers request updated assets after a new image is deployed.

Install frontend dependencies and build CSS locally:

```powershell
corepack enable
pnpm install --frozen-lockfile
pnpm run css:build
```

Watch the templates and JavaScript while changing the UI:

```powershell
pnpm run css:watch
```

Important dashboard behavior:

- the navigation changes to a mobile menu on narrow screens
- monitor and incident lists support filters and pagination
- monitor detail shows 24-hour health data and recent reliability
- incident detail shows response actions and a timeline
- settings stay collapsed until they are needed
- deleting a monitor requires confirmation and happens only from its detail page
- all HTML forms that change data require a CSRF token

The OpsWatch dashboard and Grafana have different jobs. The product dashboard manages monitors and incidents. Grafana is the internal operations interface for metrics, logs, dashboards, and alerts.

## Naming Rules

Code should use plain names that match the product:

- `Monitor`: something OpsWatch checks
- `MonitorCheck`: one saved check result
- `Incident`: a period where a monitor is failing or needs attention
- `check_monitor_endpoint`: sends one HTTP request for a monitor
- `record_monitor_check_result`: saves the result and updates incidents
- `recovery_threshold`: successful checks needed to recover

Docstrings should be short, direct, and accurate.
