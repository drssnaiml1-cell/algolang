"""Studio / Prompt UI HTTP API, served on a random local port."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import algostudio
from conftest import SIMPLE


@pytest.fixture
def server(project):
    algostudio.WORKSPACE = project
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), algostudio.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def call(base, path, body=None, origin=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method="POST" if body is not None else "GET")
    req.add_header("Content-Type", "application/json")
    if origin:
        req.add_header("Origin", origin)
    with urllib.request.urlopen(req, timeout=60) as r:
        ct = r.headers.get("Content-Type", "")
        raw = r.read()
        return json.loads(raw) if "json" in ct else raw.decode()


def test_pages_are_served(server):
    assert "AlgoLang Studio" in call(server, "/")
    assert "AlgoLang Prompt" in call(server, "/prompt")


def test_check_and_run(server):
    assert call(server, "/api/check", {"source": SIMPLE})["ok"]
    r = call(server, "/api/run", {"source": SIMPLE, "args": {"topic": "AI"}, "name": "web"})
    assert r["ok"] and r["calls"]


def test_domains_pack_compose(server):
    d = call(server, "/api/domains", {"q": "insurance claims"})
    assert d["total"] == 120 and d["packs"]
    p = call(server, "/api/pack", {"id": "insurance.claims_triage"})
    assert "agent Intake" in p["source"]
    c = call(server, "/api/compose", {"request": "our servers are down"})
    assert c["ok"]


def test_batch_and_governance(server):
    r = call(server, "/api/batch", {"source": SIMPLE, "csv": "topic\nA\nB\n", "workers": 2})
    assert r["ok"] and r["summary"]["rows"] == 2
    assert "totals" in json.dumps(call(server, "/api/report"))
    assert isinstance(call(server, "/api/reviews"), (dict, list))
    assert call(server, "/api/config")


def test_foreign_origin_is_refused(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        call(server, "/api/run", {"source": SIMPLE, "args": {"topic": "x"}}, origin="https://evil.example")
    assert e.value.code == 403


def test_local_origin_is_allowed(server):
    assert call(server, "/api/check", {"source": SIMPLE}, origin="http://127.0.0.1:8765")["ok"]
