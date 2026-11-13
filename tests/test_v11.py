"""AlgoLang v1.1: agent contracts (`ensure`), what-if audits (`algo whatif`) and governance diff (`algo diff`)."""
import json
import subprocess
import sys

import pytest

import algodiff
import algolang as al
import algoruntime as rt
import algowhatif
from algoc import CompileError, compile_source
from conftest import ROOT, write

CLAIM = (ROOT / "examples" / "v11" / "claim_contracts.algo").read_text(encoding="utf-8")
NOTE = "Policy MTR-1182: rear bumper damage, estimate 18500"


def codes(src):
    with pytest.raises(CompileError) as e:
        compile_source(src, "t.algo")
    return [d.code for d in e.value.diags]


def algo(*args, cwd=None):
    return subprocess.run([sys.executable, str(ROOT / "algoc.py"), *args], capture_output=True, text=True,
                          encoding="utf-8", cwd=cwd)


# ── agent contracts ─────────────────────────────────────────────────────────
def test_contracts_compile_into_the_policy():
    prog = al.compile(CLAIM, "claim")
    pol = prog._prog.agents["Payout"].policy
    texts = [c["text"] for c in pol["ensure"]]
    assert texts == ["result >= 0", "result <= cover"]
    assert pol["ensure"][1]["msg"] == "a payout cannot exceed the policy's cover"
    assert pol["ensure"][1]["cond"] == ["cmp", "<=", ["ref", ["result"]], ["ref", ["cover"]]]


def test_contracts_hold_and_are_audited(project):
    res = al.compile(CLAIM, "claim").run(note=NOTE, cover=200000)
    assert res.ok and not res.escalated
    payout = next(c for c in res.calls if c["agent"] == "Payout")
    assert payout["contracts"] == {"checked": 2, "held": 2, "violated": [], "redrawn": False}


def test_broken_contract_is_retried_then_goes_to_a_person(project):
    res = al.compile(CLAIM, "claim").run(note=NOTE, cover=10)
    payout = next(c for c in res.calls if c["agent"] == "Payout")
    assert payout["status"] == "escalated"
    assert payout["contracts"]["redrawn"] is True
    assert payout["contracts"]["violated"][0]["contract"] == "result <= cover"
    assert "contract violated: a payout cannot exceed" in payout["review_reason"]
    assert res.stats["contract_violations"] == 1
    queue = [json.loads(x) for x in (project / "runs" / "review_queue.jsonl").read_text().splitlines()] \
        if (project / "runs" / "review_queue.jsonl").exists() else rt.list_reviews()
    assert any("contract violated" in q["reason"] for q in queue)


def test_contracts_travel_in_algoir(project):
    import algoir
    doc = algoir.to_ir(al.compile(CLAIM, "claim")._prog, "claim", CLAIM)
    assert "result <= cover" in json.dumps(doc)


def test_contract_evaluation_rules():
    c = [{"cond": ["and", ["cmp", ">=", ["ref", ["result", "amount"]], ["lit", 0]],
                   ["contains", ["ref", ["result", "note"]], "ok", False]], "text": "t", "msg": None}]
    assert rt.contract_failures(c, {"amount": 5, "note": "OK fine"}, 0.9, {}) == []
    assert rt.contract_failures(c, {"amount": -1, "note": "ok"}, 0.9, {})[0]["message"] == "ensure t"
    # a missing field, or text where a number is needed, counts as broken (never silently passes)
    assert "cannot be checked" in rt.contract_failures(c, {"note": "ok"}, 0.9, {})[0]["message"]
    num = [{"cond": ["cmp", "<", ["ref", ["result"]], ["lit", 1]], "text": "result < 1", "msg": None}]
    assert rt.contract_failures(num, "0.4", 0.9, {}) == []           # a number written as text is a number
    assert rt.contract_failures(num, "high", 0.9, {})
    conf = [{"cond": ["cmp", ">=", ["ref", ["result", "confidence"]], ["lit", 0.8]], "text": "c", "msg": "low"}]
    assert rt.contract_failures(conf, 1, 0.5, {})[0]["message"] == "low"


@pytest.mark.parametrize("body", [
    'ensure x > 1',                        # does not check the result
    'ensure result > A(x)',                # calls an agent
    'ensure result.amount > 0',            # a score has no fields
    'ensure result > y',                   # unknown name
])
def test_bad_contracts_are_compile_errors(body):
    src = f'''agent A(x: text) -> score {{ goal "Score {{x}}" }}
agent B(x: text) -> score {{
    goal "Score {{x}}"
    {body}
}}
flow main(x: text) {{ emit B(x) }}'''
    assert "E134" in codes(src)


def test_text_results_use_contains():
    ok = '''agent W(x: text) -> text {
    goal "Write about {x}"
    ensure result not contains "guarantee" and result.confidence >= 0.5
}
flow main(x: text) { emit W(x) }'''
    compile_source(ok, "t.algo")
    assert "E134" in codes(ok.replace('result not contains "guarantee"', "result > 3"))


# ── what-if audits ──────────────────────────────────────────────────────────
def test_apply_changes_set_and_swap():
    new, ch = algowhatif.apply_changes({"cv": "She led the team. she is great", "n": "3"}, [("n", "4")], [("she", "he")])
    assert new == {"cv": "He led the team. he is great", "n": "4"}
    assert [c["kind"] for c in ch] == ["set", "swap"]
    with pytest.raises(algowhatif.WhatIfError):
        algowhatif.apply_changes({"cv": "x"}, [], [("she", "he")])
    with pytest.raises(algowhatif.WhatIfError):
        algowhatif.apply_changes({"cv": "x"}, [("nope", "1")], [])
    with pytest.raises(algowhatif.WhatIfError):
        algowhatif.apply_changes({"cv": "x"}, [("cv", "x")], [])


def test_whatif_replays_unchanged_calls_and_finds_the_flip(project):
    prog = al.compile(CLAIM, "claim", base_dir=project)
    res = prog.run(note=NOTE, cover=200000, trace=True)
    trace = json.loads(open(res.trace_path, encoding="utf-8").read())
    r = algowhatif.whatif(prog, trace["inputs"], sets=[("cover", "10")], trace=trace)
    rows = {row["agent"]: row for row in r["agents"]}
    assert rows["Intake"]["change"] == "same"                      # did not depend on the cover
    assert "review" in rows["Payout"]["change"]                    # now breaks its contract
    assert rows["Payout"]["contracts"] == {"before": [], "after": ["result <= cover"]}
    assert r["calls_recomputed"] == 2 and r["calls_total"] == 3
    assert r["decision_changed"] and r["escalated_after"] == ["Payout"]


def test_whatif_cli_expect_is_a_ci_check(project):
    prog_file = write(project / "claim.algo", CLAIM)
    r = algo("whatif", str(prog_file), "--arg", f"note={NOTE}", "--arg", "cover=200000", "--set", "cover=10",
             "--expect", "same", cwd=project)
    assert r.returncode == 1 and "the decision changed" in r.stdout
    r = algo("whatif", str(prog_file), "--arg", f"note={NOTE}", "--arg", "cover=200000", "--set", "cover=10",
             "--expect", "changed", "--json", cwd=project)
    assert r.returncode == 0 and json.loads(r.stdout)["verdict"] == "changed"
    assert algo("whatif", str(prog_file), "--arg", f"note={NOTE}", cwd=project).returncode == 2


# ── governance diff ─────────────────────────────────────────────────────────
OLD = '''risk high "Credit decisions"
disclose "An AI system assisted this decision."
tool bureau.pull
tool web.fetch untrusted
agent Score(app: text) -> uncertain<score> {
    goal "Score {app}"
    uses bureau.pull
    policy { budget tokens 2000  require human when confidence < 0.8  require approvals 2
             forbid gender, religion  explain with evidence  redact pii  samples 5 }
    ensure result >= 0 and result <= 1
}
flow main(app: text) { emit Score(app) }
eval trust on main {
    case "salaried" (app = "APP-1") { expect status ok  expect fair across gender ["woman", "man"] }
    case "self-employed" (app = "APP-2") { expect status ok }
}
'''


def changes(old, new):
    po, _ = algodiff.algoc.load_program(old, "o.algo", ROOT)
    pn, _ = algodiff.algoc.load_program(new, "n.algo", ROOT)
    return [(c["kind"], c["what"]) for c in algodiff.diff(po, pn)]


def test_no_change_means_no_diff():
    assert changes(OLD, OLD) == []


def test_every_kind_of_loosening_is_found():
    new = (OLD.replace("budget tokens 2000", "budget tokens 9000")
              .replace("confidence < 0.8", "confidence < 0.5")
              .replace("require approvals 2", "require approvals 1")
              .replace("forbid gender, religion", "forbid religion")
              .replace("explain with evidence", "explain")
              .replace("redact pii", "")
              .replace("samples 5", "samples 3")
              .replace("    ensure result >= 0 and result <= 1\n", "")
              .replace("uses bureau.pull", "uses bureau.pull, web.fetch")
              .replace("tool web.fetch untrusted", "tool web.fetch")
              .replace('risk high "Credit decisions"', 'risk limited "Credit decisions"')
              .replace('    case "self-employed" (app = "APP-2") { expect status ok }\n', "")
              .replace('  expect fair across gender ["woman", "man"]', ""))
    got = changes(OLD, new)
    assert all(k == "loosened" for k, _ in got), got
    whats = " | ".join(w for _, w in got)
    for needle in ("risk level lowered", "no longer treated as untrusted", "can now use tool 'web.fetch'",
                   "token budget raised", "human review below confidence lowered", "required approvals lowered",
                   "samples for uncertain answers lowered", "PII redaction removed",
                   "forbidden attribute 'gender' allowed again", "explanations now 'reasons'", "contract removed",
                   "case 'self-employed' removed", "expectation removed"):
        assert needle in whats, needle


def test_tightening_and_neutral_changes():
    new = OLD.replace("budget tokens 2000", "budget tokens 1000").replace('goal "Score {app}"', 'goal "Rate {app}"')
    assert changes(OLD, new) == [("tightened", "token budget lowered"), ("changed", "goal reworded")]


def test_diff_cli_exit_codes_and_markdown(project):
    o = write(project / "old.algo", OLD)
    n = write(project / "new.algo", OLD.replace("forbid gender, religion", "forbid religion"))
    r = algo("diff", str(o), str(n), cwd=project)
    assert r.returncode == 1 and "forbidden attribute 'gender' allowed again" in r.stdout
    assert algo("diff", str(n), str(o), cwd=project).returncode == 0              # tightening passes
    assert algo("diff", str(n), str(o), "--fail-on", "any", cwd=project).returncode == 1
    md = algo("diff", str(o), str(n), "--markdown", "--fail-on", "never", cwd=project)
    assert md.returncode == 0 and "| 🔻 loosened | agent Score |" in md.stdout
    js = json.loads(algo("diff", str(o), str(n), "--json", "--fail-on", "never", cwd=project).stdout)
    assert js["summary"]["loosened"] == 1
