"""AlgoLang v1.2: consensus blocks, red-team testing (`algo redteam`) and decision notices (`algo explain`)."""
import json
import subprocess
import sys

import pytest

import algodiff
import algoexplain
import algolang as al
import algoredteam
import algoruntime as rt
import algotrust
from algoc import CompileError, compile_source
from conftest import ROOT

CREDIT = (ROOT / "examples" / "v12" / "credit_consensus.algo").read_text(encoding="utf-8")
APP = "APP-7741: textile trader, 6 years trading, turnover 1.2 cr, DSCR 1.8"

HEAD = '''agent A(x: text) -> score { goal "a {x}" }
agent B(x: text) -> score { goal "b {x}" }
agent C(x: text) -> score { goal "c {x}" }
agent T(x: text) -> text { goal "t {x}" }
'''


def codes(src):
    with pytest.raises(CompileError) as e:
        compile_source(src, "t.algo")
    return [d.code for d in e.value.diags]


def algo(*args, cwd=None):
    return subprocess.run([sys.executable, str(ROOT / "algoc.py"), *args], capture_output=True, text=True,
                          encoding="utf-8", cwd=cwd)


# ── consensus: compile time ──────────────────────────────────────────────────
def test_consensus_compiles():
    compile_source(HEAD + 'flow main(x: text) {\n v = consensus 2 of { A(x), B(x), C(x) } within 0.1\n'
                          ' if v > 0.5 and v.confidence >= 0.6 { emit v }\n}\n', "t.algo")


@pytest.mark.parametrize("body", [
    "v = consensus 1 of { A(x), B(x), C(x) }",          # not a majority
    "v = consensus 4 of { A(x), B(x), C(x) }",          # more than the agents
    "v = consensus 2 of { A(x), T(x), B(x) }",          # mixed answer kinds
    "v = consensus 2 of { A(x), A(x), A(x) }",          # not independent
    "v = consensus 2 of { A(x), B(x), C(x) } within 2", # within > 1 for scores
    "v = consensus 2 of { T(x), T(x), T(x) } within 0.1",
])
def test_consensus_errors_e135(body):
    assert "E135" in codes(HEAD + f"flow main(x: text) {{\n {body}\n emit v\n}}\n")


def test_numeric_consensus_is_uncertain_so_confidence_must_be_checked():
    src = HEAD + 'flow main(x: text) {\n v = consensus 2 of { A(x), B(x), C(x) }\n if v > 0.5 { emit v }\n}\n'
    assert codes(src) == ["E117"]


# ── consensus: run time ──────────────────────────────────────────────────────
def _rt(tmp_path):
    return rt.Runtime(program="cons", quiet=True, audit_dir_override=str(tmp_path))


def _res(v, c, name):
    return lambda: rt.Result(v, c, name, name.lower())


def test_numeric_quorum_and_dissent_are_audited(tmp_path):
    r = _rt(tmp_path)
    res = r.consensus(2, [_res(0.80, 0.9, "A"), _res(0.84, 0.8, "B"), _res(0.30, 0.9, "C")], within=0.1)
    assert res.value == pytest.approx(0.82) and res.status == "ok"
    assert res.confidence == pytest.approx(round(2 / 3 * 0.85, 3))
    rec = [json.loads(x) for x in r.audit_path.read_text().splitlines()][-1]
    assert rec["type"] == "consensus" and rec["reached"] and rec["agreed"] == 2 and rec["dissent"] == ["C"]
    assert r.stats["dissents"] == 1 and r.stats["consensus"] == 1


def test_no_quorum_goes_to_a_person(tmp_path):
    r = _rt(tmp_path)
    res = r.consensus(2, [_res(0.1, 0.9, "A"), _res(0.5, 0.9, "B"), _res(0.9, 0.9, "C")], within=0.1)
    assert res.status == "escalated" and r.stats["no_consensus"] == 1 and r.stats["escalations"] == 1
    queue = [json.loads(x) for x in (tmp_path / "review_queue.jsonl").read_text().splitlines()]
    assert "no consensus: 1 of 3 agents agreed, 2 needed" in queue[-1]["reason"]


def test_text_consensus_ignores_case_and_spacing(tmp_path):
    r = _rt(tmp_path)
    res = r.consensus(2, [_res("Approve.", 0.9, "A"), _res("approve", 0.7, "B"), _res("Decline", 0.9, "C")])
    assert res.value == "Approve." and res.status == "ok"


def test_cli_runs_consensus_on_both_engines(project):
    f = project / "credit.algo"
    f.write_text(CREDIT, encoding="utf-8")
    a = algo("run", str(f), "--arg", f"app={APP}", cwd=project)
    b = algo("run", str(f), "--engine", "vm", "--arg", f"app={APP}", cwd=project)
    assert a.returncode == 0 and "⚖ consensus" in a.stdout
    emitted = lambda out: out.split("■ emitted:")[1].split("■")[0]
    assert emitted(a.stdout) == emitted(b.stdout)


def test_governance_diff_sees_a_lower_quorum(tmp_path):
    old, new = tmp_path / "old.algo", tmp_path / "new.algo"
    old.write_text(CREDIT.replace("consensus 2 of", "consensus 3 of"), encoding="utf-8")
    new.write_text(CREDIT, encoding="utf-8")
    changes = algodiff.diff(algodiff.load(str(old))[0], algodiff.load(str(new))[0])
    c = [x for x in changes if "consensus" in x["what"]]
    assert c and c[0]["kind"] == "loosened" and c[0]["before"].startswith("3 of 3")


# ── red team ─────────────────────────────────────────────────────────────────
def test_spelled_out_values_are_withheld():
    out, found = algotrust.withhold("applicant is f-e-m-a-l-e and H i n d u; Tom and Mandi", ["gender", "religion"])
    assert "f-e-m-a-l-e" not in out and "H i n d u" not in out and "Mandi" in out and "Tom and" in out
    assert found == {"gender": 1, "religion": 1}


def test_redteam_passes_a_hardened_program(project):
    team = algoredteam.RedTeam(al.compile(CREDIT, "credit"), audit_dir=str(project / "rt"))
    findings = team.run_all()
    assert findings and all(f["result"] == "PASS" for f in findings)
    probes = {f["probe"] for f in findings}
    assert {"personal data", "forbidden values", "denial of wallet"} <= probes


def test_redteam_finds_missing_safeguards(project):
    weak = CREDIT.replace("  redact pii", "").replace("budget tokens 1500  ", "")
    team = algoredteam.RedTeam(al.compile(weak, "weak"), audit_dir=str(project / "rt"))
    fails = [f for f in team.run_all() if f["result"] == "FAIL"]
    kinds = {(f["probe"], f["severity"]) for f in fails}
    assert ("personal data", "medium") in kinds and ("denial of wallet", "medium") in kinds
    assert all(f["fix"] for f in fails)


def test_redteam_tool_injection_untrusted_vs_trusted(project):
    @rt.register_tool("rtfeed.read")
    def _feed(q):
        """test feed"""
        return "feed entry for " + str(q)[:20]
    base = ('risk limited "test"\ndisclose "You are using an AI system."\ntool rtfeed.read{u}\n'
            'agent Reader(x: text) -> text {{ goal "read {{x}}"  uses rtfeed.read  policy {{ budget tokens 900  redact pii }} }}\n'
            'flow main(x: text) {{ emit Reader(x) }}\n')
    safe = algoredteam.RedTeam(al.compile(base.format(u=" untrusted"), "safe"), audit_dir=str(project / "a")).run_all()
    open_ = algoredteam.RedTeam(al.compile(base.format(u=""), "open"), audit_dir=str(project / "b")).run_all()
    inj = lambda fs: next(f for f in fs if f["probe"] == "tool injection")
    assert inj(safe)["result"] == "PASS"
    assert inj(open_)["result"] == "FAIL" and inj(open_)["severity"] == "medium"


def test_redteam_cli_exit_codes(project):
    f = project / "credit.algo"
    f.write_text(CREDIT, encoding="utf-8")
    ok = algo("redteam", str(f), "--json", cwd=project)
    assert ok.returncode == 0 and json.loads(ok.stdout)["summary"]["failed"] == 0
    w = project / "weak.algo"
    w.write_text(CREDIT.replace("  redact pii", ""), encoding="utf-8")
    assert algo("redteam", str(w), cwd=project).returncode == 0                  # medium < default high
    md = project / "rt.md"
    bad = algo("redteam", str(w), "--fail-on", "medium", "--markdown", str(md), cwd=project)
    assert bad.returncode == 1 and "personal data" in md.read_text(encoding="utf-8")


# ── decision notices ─────────────────────────────────────────────────────────
def test_explain_builds_a_notice_from_trace_and_audit(project):
    res = al.compile(CREDIT, "credit").run(app=APP, trace=True, audit_dir=str(project / "runs"))
    trace = json.loads(open(res.trace_path, encoding="utf-8").read())
    n = algoexplain.build(trace, res.audit_path, contact="cto@algoprofessor.com", program=al.compile(CREDIT, "credit"))
    assert n["reference"] == res.run_id and n["contact"] == "cto@algoprofessor.com"
    assert n["purpose"].startswith("Pre-screening")
    kinds = [s["kind"] for s in n["steps"]]
    assert kinds.count("agent") == len([c for c in res.calls if c.get("type") != "consensus"]) and "consensus" in kinds
    assert any("not allowed to use: gender, religion" in s for s in n["safeguards"])
    assert n["integrity"]["intact"] and n["integrity"]["records"] == len(res.calls)
    md = algoexplain.to_markdown(n)
    assert "## Your rights" in md and "cto@algoprofessor.com" in md and "out of 1" in md
    assert "<html" in algoexplain.to_html(n)


def test_explain_reports_a_pending_decision(project):
    res = al.compile(CREDIT.replace("within 0.15", "within 0.001").replace("consensus 2 of", "consensus 3 of"),
                     "credit").run(app=APP, trace=True, audit_dir=str(project / "runs"))
    trace = json.loads(open(res.trace_path, encoding="utf-8").read())
    n = algoexplain.build(trace, res.audit_path)
    assert n["outcome"]["state"] == "pending"
    assert "a person will decide" in algoexplain.to_markdown(n)


def test_explain_cli(project):
    f = project / "credit.algo"
    f.write_text(CREDIT, encoding="utf-8")
    page = project / "notice.html"
    r = algo("explain", str(f), "--arg", f"app={APP}", "--html", str(page), "--contact", "cto@algoprofessor.com",
             cwd=project)
    assert r.returncode == 0 and "Notice of an AI-assisted decision" in page.read_text(encoding="utf-8")
    j = algo("explain", str(f), "--arg", f"app={APP}", "--json", cwd=project)
    assert json.loads(j.stdout)["outcome"]["state"] in ("decided", "pending")
