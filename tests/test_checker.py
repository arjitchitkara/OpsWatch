from types import SimpleNamespace

import httpx

from opswatch.monitoring.http_checks import check_monitor_endpoint


def make_monitor(**overrides):
    data = {
        "method": "GET",
        "url": "https://example.test/health",
        "expected_status": 200,
        "expected_body": None,
        "timeout_seconds": 1,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_successful_check():
    client = client_for(lambda request: httpx.Response(200, text="ok"))
    result = check_monitor_endpoint(make_monitor(expected_body="ok"), client)
    assert result.success is True
    assert result.status_code == 200
    assert result.error_type is None


def test_unexpected_status():
    client = client_for(lambda request: httpx.Response(500, text="nope"))
    result = check_monitor_endpoint(make_monitor(), client)
    assert result.success is False
    assert result.error_type == "unexpected_status"


def test_expected_body_missing():
    client = client_for(lambda request: httpx.Response(200, text="different"))
    result = check_monitor_endpoint(make_monitor(expected_body="healthy"), client)
    assert result.success is False
    assert result.error_type == "expected_body_missing"


def test_timeout_error():
    def handler(request):
        raise httpx.TimeoutException("too slow", request=request)

    result = check_monitor_endpoint(make_monitor(), client_for(handler))
    assert result.success is False
    assert result.error_type == "timeout"


def test_request_error():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    result = check_monitor_endpoint(make_monitor(), client_for(handler))
    assert result.success is False
    assert result.error_type == "request_error"
