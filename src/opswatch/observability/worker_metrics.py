from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from time import perf_counter


class WorkerMetrics:
    """Store worker metrics in memory."""

    def __init__(self) -> None:
        """Create empty worker metrics."""

        self._lock = Lock()
        self.loop_runs_total = 0
        self.loop_failures_total = 0
        self.loop_duration_seconds_sum = 0.0
        self.loop_duration_seconds_count = 0
        self.monitor_check_total: dict[tuple[str, str], int] = defaultdict(int)
        self.monitor_check_duration_seconds_sum: dict[tuple[str, str], float] = defaultdict(float)
        self.monitor_check_duration_seconds_count: dict[tuple[str, str], int] = defaultdict(int)
        self.monitor_check_skipped_total: dict[str, int] = defaultdict(int)

    def reset(self) -> None:
        """Clear all metric values."""

        with self._lock:
            self.loop_runs_total = 0
            self.loop_failures_total = 0
            self.loop_duration_seconds_sum = 0.0
            self.loop_duration_seconds_count = 0
            self.monitor_check_total.clear()
            self.monitor_check_duration_seconds_sum.clear()
            self.monitor_check_duration_seconds_count.clear()
            self.monitor_check_skipped_total.clear()

    def record_loop_run(self, duration_seconds: float) -> None:
        """Record one completed worker loop."""

        with self._lock:
            self.loop_runs_total += 1
            self.loop_duration_seconds_sum += duration_seconds
            self.loop_duration_seconds_count += 1

    def record_loop_failure(self) -> None:
        """Record one failed worker loop."""

        with self._lock:
            self.loop_failures_total += 1

    def record_monitor_check(self, success: bool, error_type: str | None, duration_seconds: float | None) -> None:
        """Record one monitor check result."""

        result_label = "success" if success else "failure"
        error_label = error_type or "none"
        label_key = (result_label, error_label)
        with self._lock:
            self.monitor_check_total[label_key] += 1
            if duration_seconds is not None:
                self.monitor_check_duration_seconds_sum[label_key] += duration_seconds
                self.monitor_check_duration_seconds_count[label_key] += 1

    def record_monitor_check_skip(self, reason: str) -> None:
        """Record one skipped monitor check."""

        with self._lock:
            self.monitor_check_skipped_total[reason] += 1

    def render_prometheus_text(self) -> str:
        """Return worker metrics in Prometheus text format."""

        with self._lock:
            lines = [
                "# HELP opswatch_worker_loop_runs_total Total worker loops that finished.",
                "# TYPE opswatch_worker_loop_runs_total counter",
                f"opswatch_worker_loop_runs_total {self.loop_runs_total}",
                "# HELP opswatch_worker_loop_failures_total Total worker loops that failed.",
                "# TYPE opswatch_worker_loop_failures_total counter",
                f"opswatch_worker_loop_failures_total {self.loop_failures_total}",
                "# HELP opswatch_worker_loop_duration_seconds Worker loop duration in seconds.",
                "# TYPE opswatch_worker_loop_duration_seconds summary",
                f"opswatch_worker_loop_duration_seconds_count {self.loop_duration_seconds_count}",
                f"opswatch_worker_loop_duration_seconds_sum {self.loop_duration_seconds_sum:.6f}",
                "# HELP opswatch_worker_monitor_checks_total Total monitor checks run by the worker.",
                "# TYPE opswatch_worker_monitor_checks_total counter",
            ]
            for (result_label, error_label), value in sorted(self.monitor_check_total.items()):
                lines.append(
                    f'opswatch_worker_monitor_checks_total{{error_type="{error_label}",result="{result_label}"}} {value}'
                )

            lines.extend(
                [
                    "# HELP opswatch_worker_monitor_check_duration_seconds Monitor check duration in seconds.",
                    "# TYPE opswatch_worker_monitor_check_duration_seconds summary",
                ]
            )
            for (result_label, error_label), value in sorted(self.monitor_check_duration_seconds_count.items()):
                lines.append(
                    f'opswatch_worker_monitor_check_duration_seconds_count{{error_type="{error_label}",result="{result_label}"}} {value}'
                )
            for (result_label, error_label), value in sorted(self.monitor_check_duration_seconds_sum.items()):
                lines.append(
                    f'opswatch_worker_monitor_check_duration_seconds_sum{{error_type="{error_label}",result="{result_label}"}} {value:.6f}'
                )

            lines.extend(
                [
                    "# HELP opswatch_worker_monitor_check_skipped_total Total monitor checks skipped by the worker.",
                    "# TYPE opswatch_worker_monitor_check_skipped_total counter",
                ]
            )
            for reason, value in sorted(self.monitor_check_skipped_total.items()):
                lines.append(f'opswatch_worker_monitor_check_skipped_total{{reason="{reason}"}} {value}')

        return "\n".join(lines) + "\n"


worker_metrics = WorkerMetrics()


class WorkerMetricsRequestHandler(BaseHTTPRequestHandler):
    """Serve worker metrics over HTTP."""

    def do_GET(self) -> None:
        """Return metrics or health data for one GET request."""

        if self.path == "/metrics":
            body = worker_metrics.render_prometheus_text().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path in {"/health", "/ready"}:
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, message_format: str, *args) -> None:
        """Disable default HTTP request logging."""


def start_worker_metrics_server(port: int) -> ThreadingHTTPServer:
    """Start the worker metrics HTTP server in a background thread."""

    server = ThreadingHTTPServer(("0.0.0.0", port), WorkerMetricsRequestHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class WorkerLoopTimer:
    """Measure one worker loop."""

    def __enter__(self):
        """Start timing one worker loop."""

        self.started_at = perf_counter()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        """Record worker loop duration and failure state."""

        worker_metrics.record_loop_run(perf_counter() - self.started_at)
        if exc_type is not None:
            worker_metrics.record_loop_failure()
