"""#362 (#130 §5.4): the Solana debug signature endpoints are gone.

They took no sign-in and were open whenever CRYPTO_ADMIN_KEY was unset; the app never called them.
"""

import pytest


@pytest.mark.parametrize("path", ["/crypto/debug/verify-sig", "/crypto/debug/verify-bytes"])
def test_debug_signature_endpoints_are_gone(client, path):
    resp = client.post(path, json={"address": "x", "message_bytes_b64": "", "signature": "x"})
    assert resp.status_code == 404


def test_debug_routes_are_not_registered():
    from app.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    assert not any(p.startswith("/crypto/debug") for p in paths)
