from monitoring import prober
from prometheus_client import REGISTRY


def test_full_round_includes_real_post_and_slow_response_is_bad(monkeypatch):
    responses = iter([(True, .1, 200, '<a href="/author/42/">post</a>'), (True, 1.2, 200, "site-main")])
    urls = []
    def check(url, expected):
        urls.append(url)
        return next(responses)
    monkeypatch.setattr(prober, "check", check)
    prober.run_round("http://blog-web")
    assert urls == ["http://blog-web/", "http://blog-web/author/42/"]
    assert REGISTRY.get_sample_value("blog_probe_round_good") == 0
    assert REGISTRY.get_sample_value("blog_probe_success", {"target": "post"}) == 1


def test_bad_feed_marks_entire_round_bad(monkeypatch):
    monkeypatch.setattr(prober, "check", lambda *args: (False, .1, 503, "unavailable"))
    prober.run_round("http://blog-web")
    assert REGISTRY.get_sample_value("blog_probe_round_good") == 0
    assert REGISTRY.get_sample_value("blog_probe_success", {"target": "post"}) == 0


def test_http_check_checks_body_and_handles_connection_failure(monkeypatch):
    from io import BytesIO
    class Response(BytesIO):
        status = 200
    monkeypatch.setattr(prober, "urlopen", lambda *args, **kwargs: Response(b"wrong content"))
    assert prober.check("http://example/", "site-main")[0] is False
    def unavailable(*args, **kwargs):
        raise OSError("network unavailable")
    monkeypatch.setattr(prober, "urlopen", unavailable)
    success, duration, status, _ = prober.check("http://example/", "site-main")
    assert not success and duration >= 0 and status == 0
