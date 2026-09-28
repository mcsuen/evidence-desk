import socket
from datetime import datetime,timezone,timedelta
import httpx
import pytest
from pitr.adapters.public_fetch import fetch_public,FetchError,retry_after

@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [(2, 1, 6, '', ('8.8.8.8', 443))])


def test_default_identity_sec_configuration_and_redirect_scope(public_dns, monkeypatch):
    seen = []
    def serve(request):
        seen.append(request)
        return httpx.Response(302, headers={'location': 'https://issuer.example.com/report'}) if request.url.host == 'www.sec.gov' else httpx.Response(200, content=b'original')
    client = httpx.Client(transport=httpx.MockTransport(serve))
    with pytest.raises(FetchError) as error:fetch_public('https://www.sec.gov/report', client=client)
    assert error.value.kind == 'configuration_required' and not seen
    assert error.value.receipts[0]['phase'] == 'configuration'
    fetch_public('https://www.sec.gov/report', client=client, contact='PITR test@example.com')
    assert seen[0].headers['User-Agent'] == 'PITR test@example.com'
    assert seen[1].headers['User-Agent'].startswith('python-httpx/')
    assert 'test@example.com' not in str(seen[1].headers)


def test_connection_retry_is_bounded_and_attempts_preserved(public_dns, monkeypatch):
    monkeypatch.setattr('pitr.adapters.public_fetch.time.sleep', lambda _: None)
    calls = []
    def serve(request):
        calls.append(request)
        raise httpx.ConnectError('SSL handshake terminated')
    client = httpx.Client(transport=httpx.MockTransport(serve))
    with pytest.raises(httpx.ConnectError) as error:fetch_public('https://example.com/report', client=client)
    assert len(calls) == 3
    assert len(error.value.receipts) == 3
    assert all(r['status'] is None and r['error_type'] == 'tls_error' and 'elapsed_seconds' in r for r in error.value.receipts)


def test_dns_failures_obey_the_same_retry_limit(monkeypatch):
    monkeypatch.setattr('pitr.adapters.public_fetch.time.sleep', lambda _: None)
    def fail_dns(*args, **kwargs):raise socket.gaierror('DNS unavailable')
    monkeypatch.setattr(socket, 'getaddrinfo', fail_dns)
    with pytest.raises(socket.gaierror) as error:
        fetch_public('https://example.com/report', client=httpx.Client(transport=httpx.MockTransport(lambda _:pytest.fail('no HTTP before DNS'))))
    assert len(error.value.receipts) == 3
    assert all(r['phase'] == 'connect' and r['status'] is None for r in error.value.receipts)


@pytest.mark.parametrize('status', [401, 403, 404])
def test_denial_is_not_retried(public_dns, status):
    calls = []
    def serve(request):calls.append(request);return httpx.Response(status)
    with pytest.raises(FetchError) as error:fetch_public('https://example.com/report', client=httpx.Client(transport=httpx.MockTransport(serve)))
    assert len(calls) == 1 and not error.value.retryable


def test_rate_limit_wait_or_defer_respects_remaining_budget(public_dns, monkeypatch):
    sleeps, calls = [], []
    monkeypatch.setattr('pitr.adapters.public_fetch.time.sleep', lambda wait: sleeps.append(wait))
    def serve(request):
        calls.append(request)
        return httpx.Response(429, headers={'Retry-After': '3'}) if len(calls) == 1 else httpx.Response(200, content=b'original')
    client = httpx.Client(transport=httpx.MockTransport(serve))
    assert fetch_public('https://example.com/report', client=client)[0] == b'original'
    assert sleeps == [3] and len(calls) == 2
    calls.clear();sleeps.clear()
    with pytest.raises(FetchError) as error:fetch_public('https://example.com/report', timeout=2, client=client)
    assert error.value.kind == 'rate_limited' and len(calls) == 1 and not sleeps
    date = (datetime.now(timezone.utc) + timedelta(seconds=30)).strftime('%a, %d %b %Y %H:%M:%S GMT')
    assert 28 <= retry_after(date) <= 30
