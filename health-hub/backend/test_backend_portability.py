"""Portable defaults for optional host-specific integrations."""
import dashboard


def test_scale_bridge_is_disabled_without_explicit_configuration(monkeypatch):
    monkeypatch.delenv("HEALTH_DASHBOARD_URL", raising=False)
    monkeypatch.delenv("HEALTH_SCALE_USER", raising=False)
    monkeypatch.setattr(dashboard, "_scale_cache", None)
    monkeypatch.setattr(dashboard, "_scale_at", 0)

    def unexpected_request(*_args, **_kwargs):
        raise AssertionError("unconfigured optional integration made a request")

    monkeypatch.setattr(dashboard, "urlopen", unexpected_request)
    assert dashboard._scale_data() is None


def test_scale_bridge_uses_configured_host_and_encoded_user(monkeypatch):
    requested = []

    class Response:
        def __init__(self, value):
            self.value = value

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.value

    import json

    def fake_urlopen(url, timeout):
        requested.append((url, timeout))
        return Response(json.dumps({"endpoint": url}).encode())

    monkeypatch.setenv("HEALTH_DASHBOARD_URL", "https://scales.example/health/")
    monkeypatch.setenv("HEALTH_SCALE_USER", "family member")
    monkeypatch.setattr(dashboard, "_scale_cache", None)
    monkeypatch.setattr(dashboard, "_scale_at", 0)
    monkeypatch.setattr(dashboard, "urlopen", fake_urlopen)

    data = dashboard._scale_data()
    assert len(requested) == 2
    assert all(url.startswith("https://scales.example/health/api/") for url, _ in requested)
    assert all("user=family%20member&range=all" in url for url, _ in requested)
    assert data["composition"]["endpoint"] == requested[0][0]
