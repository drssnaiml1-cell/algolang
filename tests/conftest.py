"""Shared fixtures. Every test runs in its own temporary folder with fresh configuration,
so audit logs, review queues and caches never leak between tests."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import algoruntime as rt  # noqa: E402


@pytest.fixture(autouse=True)
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("ALGO_CONFIG", "ALGO_LIVE", "ALGO_INTERACTIVE", "ALGO_NOTEBOOK", "ALGO_PACKS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ALGO_AUDIT_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("NO_COLOR", "1")
    before = dict(rt.TOOLS)
    rt._CONFIG = None
    rt.load_config(reload=True)
    yield tmp_path
    rt.TOOLS.clear()
    rt.TOOLS.update(before)
    rt._CONFIG = None


@pytest.fixture
def root():
    return ROOT


def write(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


SIMPLE = '''
agent Echo(topic: text) -> text {
    role "Echo"
    goal "Repeat {topic}"
}
flow main(topic: text) {
    a = Echo(topic)
    emit a
}
'''
