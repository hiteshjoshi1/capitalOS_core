from app.main import _resolve_cors_origins


def test_resolve_cors_origins_uses_local_defaults_when_unset() -> None:
    origins = _resolve_cors_origins("")
    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1:5173" in origins
    assert "http://localhost:4173" in origins
    assert "http://127.0.0.1:4173" in origins


def test_resolve_cors_origins_adds_localhost_aliases() -> None:
    origins = _resolve_cors_origins("http://localhost:5173")
    assert origins == ["http://127.0.0.1:5173", "http://localhost:5173"]


def test_resolve_cors_origins_keeps_custom_origins() -> None:
    origins = _resolve_cors_origins("https://app.example.com,http://127.0.0.1:5173")
    assert "https://app.example.com" in origins
    assert "http://127.0.0.1:5173" in origins
    assert "http://localhost:5173" in origins
