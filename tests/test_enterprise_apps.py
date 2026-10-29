"""Every enterprise application passes its behaviour tests and its sample batch job."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS = ROOT / "enterprise-apps"


def test_every_app_has_the_full_layout():
    apps = [p for p in APPS.iterdir() if (p / "algo.config.json").exists()]
    assert len(apps) >= 8
    for app in apps:
        for part in ("README.md", "plugins", "programs", "data", "tests"):
            assert (app / part).exists(), f"{app.name} is missing {part}"
        assert list((app / "tests").glob("*.algotest.json")), f"{app.name} has no behaviour tests"


def test_all_apps_pass_tests_and_batch():
    r = subprocess.run([sys.executable, str(APPS / "run_all.py"), "--batch"], capture_output=True, text=True,
                       env={**os.environ, "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    assert "all applications pass" in r.stdout
