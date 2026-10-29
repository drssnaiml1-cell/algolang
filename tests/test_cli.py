"""The `algo` command line, run as a real subprocess."""
import json
import subprocess
import sys

import pytest

from conftest import ROOT


def algo(*args, cwd=None, inp=None):
    p = subprocess.run([sys.executable, str(ROOT / "algoc.py"), *args], cwd=cwd, input=inp,
                       capture_output=True, text=True, encoding="utf-8", timeout=120,
                       env={**__import__("os").environ, "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"})
    return p.returncode, p.stdout + p.stderr


def test_doctor():
    code, out = algo("doctor")
    assert code == 0 and "Ready" in out


def test_check_good_and_bad():
    assert algo("check", str(ROOT / "examples" / "research_brief.algo"))[0] == 0
    code, out = algo("check", str(ROOT / "examples" / "bad_example.algo"))
    assert code != 0 and "E101" in out


def test_run_example(project):
    code, out = algo("run", str(ROOT / "examples" / "research_brief.algo"), "--arg", "topic=Testing", cwd=project)
    assert code == 0 and "emitted" in out


def test_enterprise_project_flow(project):
    assert algo("init", ".", cwd=project)[0] == 0
    assert (project / "algo.config.json").exists()
    code, out = algo("domains", "insurance claims", cwd=project)
    assert "insurance.claims_triage" in out
    code, out = algo("run", "pack:insurance.claims_triage", "--arg", "claim=dent", cwd=project)
    assert code == 0
    code, out = algo("batch", "programs/claims_ops.algo", "--input", "data/claims.csv", "--out", "res.csv", cwd=project)
    assert code == 0 and (project / "res.csv").exists()
    assert algo("audit", "verify", cwd=project)[0] == 0
    code, out = algo("report", "--json", cwd=project)
    assert json.loads(out[out.index("{"):])["totals"]["calls"] > 0
    assert algo("review", cwd=project)[0] == 0


def test_dev_track(project):
    algo("init", ".", cwd=project)
    assert algo("dev", "new-tool", "company.payroll", cwd=project)[0] == 0
    assert algo("dev", "new-pack", "logistics.customs_check", "--pattern", "committee", cwd=project)[0] == 0
    assert algo("dev", "lint", ".", cwd=project)[0] == 0
    code, out = algo("dev", "test", ".", cwd=project)
    assert code == 0, out
    code, out = algo("dev", "graph", "programs/claims_ops.algo", cwd=project)
    assert out.startswith("flowchart TD")
    assert algo("dev", "ci", cwd=project)[0] == 0
    assert (project / ".github" / "workflows" / "algolang.yml").exists()


def test_dev_test_reports_failures(project):
    (project / "p.algo").write_text('agent A(x: text) -> text { role "r" goal "g {x}" }\n'
                                    'flow main(x: text) { y = A(x) emit y }\n')
    (project / "p.algotest.json").write_text(json.dumps({"program": "p.algo", "cases": [
        {"name": "impossible", "inputs": {"x": "hi"}, "expect": {"max_tokens": 1}}]}))
    code, out = algo("dev", "test", ".", cwd=project)
    assert code == 1 and "max 1" in out


@pytest.mark.parametrize("cmd", [["shell"]])
def test_shell_session(project, cmd):
    script = ('agent A(x: text) -> text { role "r" goal "g {x}" }\n'
              'flow main(x: text) { y = A(x) emit y }\n:run x=hi\n:quit\n')
    code, out = algo(*cmd, cwd=project, inp=script)
    assert "emitted" in out
