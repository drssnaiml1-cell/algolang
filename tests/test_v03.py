"""AlgoLang v0.3: uncertain<T>, eval blocks + trace replay, MCP tool bindings, cost/energy budgets, the LSP."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import algolang as al
import algoruntime as rt
from algoc import CompileError, compile_source
from conftest import ROOT, write

RISK = '''
agent RiskJudge(claim: text) -> uncertain<score> {
    role "Fraud risk judge"
    goal "Score 0 to 1 the fraud risk of {claim}"
    policy { samples 5 }
}
agent Refer(claim: text) -> text { goal "Write a referral for {claim}" }
agent Settle(claim: text) -> text { goal "Settle {claim}" }
flow main(claim: text) {
    risk = RiskJudge(claim)
    if risk > 0.95 and risk.confidence >= 0.5 {
        emit risk, Refer(claim)
    } else {
        emit risk, Settle(claim)
    }
}
'''


def codes(src):
    with pytest.raises(CompileError) as e:
        compile_source(src, "t.algo")
    return [d.code for d in e.value.diags]


# ───────────────────────────── uncertain<T> ─────────────────────────────
def test_uncertain_agent_is_sampled_and_aggregated():
    r = al.compile(RISK, "risk").run(claim="Rear-end collision NS-10234", trace=True)
    assert r.ok
    call = [c for c in r.calls if c["agent"] == "RiskJudge"][0]
    assert call["samples"] == 5 and call["spread"] is not None and 0 <= call["confidence"] <= 1
    rec = [c for c in json.loads(Path(r.trace_path).read_text())["calls"] if c["agent"] == "RiskJudge"][0]
    samples = [s["value"] for s in rec["samples"]]
    assert len(samples) == 5 and len(set(samples)) > 1                # repeated samples differ
    assert abs(r.values[0] - sum(samples) / 5) < 1e-3                 # score → mean of the samples
    assert "Settle" in [c["agent"] for c in r.calls]                   # risk ≤ 0.95 → else branch


def test_uncertain_comparison_needs_a_confidence_guard():
    bad = RISK.replace("if risk > 0.95 and risk.confidence >= 0.5 {", "if risk > 0.95 {")
    assert "E117" in codes(bad)
    ok = RISK.replace("if risk > 0.95 and risk.confidence >= 0.5 {", "if risk.confidence < 0.4 or risk > 0.95 {")
    compile_source(ok, "t.algo")                                     # guard anywhere in the condition counts


def test_confidence_only_on_agent_results_and_unit_checks():
    src = '''agent A(x: text) -> score { goal "g {x}" policy { samples 40 budget cost 1 eur budget energy 3 joules } }
flow main(x: text) { a = A(x) if x.confidence > 0.5 { emit a } if a.value > 1 { emit a } }'''
    c = codes(src)
    assert c.count("E121") == 3 and c.count("E118") == 2


def test_condition_and_or_codegen_runs():
    src = '''agent A(x: text) -> score { goal "g {x}" }
agent B(x: text) -> score { goal "h {x}" }
flow main(x: text) { a = A(x)  b = B(x)  if a > 2 or b < 2 and b.confidence > 0 { emit "yes" } else { emit "no" } }'''
    assert al.compile(src, "c").run(x="q").values == ["yes"]


# ───────────────────────────── cost & energy ─────────────────────────────
def test_every_call_is_priced_in_money_and_energy():
    r = al.compile(RISK, "risk").run(claim="x")
    assert r.stats["cost_usd"] > 0 and r.stats["energy_wh"] > 0 and r.stats["co2_g"] > 0
    assert all("cost_usd" in c and "energy_wh" in c for c in r.calls)


def test_cost_budget_blocks_before_the_call():
    src = RISK.replace("policy { samples 5 }", "policy { samples 5  budget cost 0.000001 usd }")
    r = al.compile(src, "risk").run(claim="x")
    assert r.status == "blocked" and "budget" in r.problem
    assert not [c for c in r.calls if c["agent"] == "RiskJudge" and c.get("status") != "blocked"]


def test_inr_and_energy_budgets_and_merge_rule():
    src = '''policy { budget cost 1 inr }
agent A(x: text) -> text { goal "g {x}" policy { budget energy 0.000001 wh } }
flow main(x: text) { emit A(x) }'''
    _, prog = compile_source(src, "t.algo")
    assert prog.agents["A"].policy["budget_cost_inr"] == 1.0
    r = al.compile(src, "e").run(x="x")
    assert r.status == "blocked" and "Wh" in r.problem


def test_run_level_caps_from_config(project):
    write(project / "algo.config.json", json.dumps({"max_run_cost_usd": 0.0000001}))
    rt.load_config(reload=True)
    r = al.compile(RISK, "risk").run(claim="x")
    assert r.status == "blocked" and "cap" in r.problem


def test_live_backend_prices_input_and_output_tokens_separately():
    class B:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class Msgs:
        def create(self, **kw):
            return B(stop_reason="end_turn", usage=B(input_tokens=1000, output_tokens=2000),
                     content=[B(type="text", text='{"value": "ok", "confidence": 0.9}')])

    r = al.compile('agent A(x: text) -> text { goal "g {x}" }\nflow main(x: text) { emit A(x) }', "l") \
        .run(x="x", backend=rt.ClaudeBackend(client=B(messages=Msgs())))
    # default sonnet placeholder price: $3 / $15 per million tokens
    assert abs(r.stats["cost_usd"] - (1000 * 3 + 2000 * 15) / 1e6) < 1e-9


def test_report_totals_include_cost_and_energy(project):
    al.compile(RISK, "risk").run(claim="x")
    rep = al.audit.report(str(project / "runs"))
    assert rep["totals"]["cost_usd"] > 0 and rep["programs"]["risk"]["energy_wh"] > 0


# ───────────────────────────── eval + replay ─────────────────────────────
EVAL = RISK + '''
eval regression on main {
    case "settles" (claim = "Rear-end collision NS-10234") {
        expect status ok
        expect called Settle
        expect not called Refer
        expect tokens < 5000
        expect cost < 0.1
        expect emits 2
    }
    case "fails on purpose" (claim = "x") {
        expect called Refer
    }
}
'''


def test_eval_blocks_run_and_record_traces(project):
    import algoeval
    p = write(project / "risk.algo", EVAL)
    prog = al.load(p)
    assert [c.name for c in prog.evals[0].cases] == ["settles", "fails on purpose"]
    res = algoeval.run_evals(prog)
    assert [r["passed"] for r in res] == [True, False]
    assert "Refer was not called" in res[1]["failures"]
    assert all(Path(r["trace"]).exists() for r in res)
    replayed = algoeval.run_evals(prog, replay="")
    assert [r["passed"] for r in replayed] == [True, False]
    assert replayed[0]["stats"]["tokens"] == 0 and replayed[0]["replay"]["hits"] == 2


def test_replay_detects_changed_prompts(project):
    import algoeval
    p = write(project / "risk.algo", RISK)
    r = al.load(p).run(claim="Water damage", trace=True)
    same = algoeval.replay_trace(r.trace_path)
    assert same["status"] == "ok" and not same["misses"] and same["same_outputs"]
    p.write_text(RISK.replace('goal "Settle {claim}"', 'goal "Settle {claim} within 7 days"'), encoding="utf-8")
    changed = algoeval.replay_trace(r.trace_path)
    assert changed["source_changed"] and changed["status"] == "failed"
    assert [m["agent"] for m in changed["misses"]] == ["Settle"]


def test_eval_compile_errors():
    src = RISK + '''eval e on nope { case "a" (claim = "x") { expect called Ghost } }
eval f on main { case "b" (wrong = "x") { expect called Ghost  expect status sideways } }'''
    assert codes(src).count("E119") >= 4


# ───────────────────────────── MCP ─────────────────────────────
@pytest.fixture
def mcp_project(project):
    shutil.copy(ROOT / "examples" / "v03" / "mcp_demo_server.py", project / "mcp_demo_server.py")
    write(project / "algo.config.json", json.dumps(
        {"mcp_servers": {"company-kb": {"command": "{python}", "args": ["mcp_demo_server.py"]}}}))
    rt.load_config(reload=True)
    yield project
    import algomcp
    algomcp.close_all()


def test_mcp_client_lists_and_calls_tools(mcp_project):
    import algomcp
    c = algomcp.client("company-kb")
    assert {"search_policies", "convert_to_inr"} <= set(c.tools())
    assert "INR 25,200.00" in c.call("convert_to_inr", {"text": "fee USD 300"})
    assert c.call("exchange_rate", {"base": "XXX", "quote": "INR"}).startswith("tool error")


def test_program_tools_bound_to_mcp(mcp_project):
    src = '''tool kb.search_policies from mcp "company-kb"
agent Finder(q: text) -> text { goal "Find the travel policy for {q}" uses kb.search_policies }
flow main(q: text) { emit Finder(q) }'''
    r = al.compile(src, "m").run(q="hotel nights travel")
    call = r.calls[0]
    assert call["tool_calls"][0]["tool"] == "kb.search_policies"
    assert "Travel" in str(rt.Runtime.value(r.values[0]))


def test_unknown_mcp_server_is_a_compile_error(mcp_project):
    assert "E120" in codes('tool x.y from mcp "nowhere"\nagent A(q: text) -> text { goal "g {q}" uses x.y }\n'
                           'flow main(q: text) { emit A(q) }')


def test_v03_example_evals_pass(root):
    out = subprocess.run([sys.executable, str(root / "algoc.py"), "eval", "expense_desk.algo", "--json"],
                         cwd=root / "examples" / "v03", capture_output=True, text=True, timeout=120)
    res = json.loads(out.stdout)
    assert out.returncode == 0 and res["failed"] == 0, out.stdout[-2000:]


# ───────────────────────────── LSP ─────────────────────────────
class LSP:
    def __init__(self, root):
        self.p = subprocess.Popen([sys.executable, str(root / "algoc.py"), "lsp"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE)
        self.i = 0

    def send(self, method, params=None, request=True):
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if request:
            self.i += 1
            msg["id"] = self.i
        b = json.dumps(msg).encode()
        self.p.stdin.write(f"Content-Length: {len(b)}\r\n\r\n".encode() + b)
        self.p.stdin.flush()
        return self.recv() if request else None

    def recv(self):
        h = {}
        while True:
            line = self.p.stdout.readline().decode().strip()
            if not line:
                break
            k, _, v = line.partition(":")
            h[k.lower()] = v.strip()
        return json.loads(self.p.stdout.read(int(h["content-length"])))

    def close(self):
        self.send("shutdown")
        self.send("exit", request=False)
        return self.p.wait(timeout=10)


def test_language_server(project, root):
    src = 'use pack insurance.claims_triage as claims\nagent Note(c: text) -> text { goal "note {c}" }\n' \
          'flow main(claim: text) {\n    c = claims.Intake(claim)\n    emit Note(c)\n}\n'
    f = write(project / "lsp.algo", src)
    uri = f.resolve().as_uri()
    s = LSP(root)
    assert "hoverProvider" in s.send("initialize")["result"]["capabilities"]
    s.send("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": "algolang", "version": 1,
                                                     "text": src.replace("emit Note(c)", "emit Missing(c)")}}, False)
    diags = s.recv()["params"]["diagnostics"]
    assert diags and diags[0]["code"] == "E101" and diags[0]["range"]["start"]["line"] == 4
    s.send("textDocument/didChange", {"textDocument": {"uri": uri, "version": 2}, "contentChanges": [{"text": src}]},
           False)
    assert s.recv()["params"]["diagnostics"] == []
    hover = s.send("textDocument/hover", {"textDocument": {"uri": uri}, "position": {"line": 3, "character": 14}})
    assert "agent claims.Intake(claim: text) -> text" in hover["result"]["contents"]["value"]
    d = s.send("textDocument/definition", {"textDocument": {"uri": uri}, "position": {"line": 3, "character": 14}})
    assert d["result"]["uri"].endswith("packs/insurance/claims_triage.algo")
    comp = s.send("textDocument/completion", {"textDocument": {"uri": uri}, "position": {"line": 0, "character": 13}})
    assert any(i["label"] == "insurance.fraud_screening" for i in comp["result"]["items"])
    syms = s.send("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
    assert [x["name"] for x in syms["result"]][:2] == ["Note", "flow main"]
    assert s.close() == 0


# ───────────────────────────── deterministic guards ─────────────────────────────
def test_contains_guard_is_deterministic_and_searches_tool_output():
    rt.register_tool("limits.check", "test limits")(lambda q: "BREACH: 15 lots > limit 10" if "15" in q else "WITHIN LIMITS")
    src = '''tool limits.check
agent Limits(order: text) -> text { goal "Check {order}" uses limits.check }
agent Gate(order: text) -> score { goal "Score {order}" }
agent Reject(order: text) -> text { goal "Reject {order}" }
agent Ticket(order: text) -> text { goal "Ticket {order}" }
flow main(order: text) {
    limits = Limits(order)
    if limits contains "breach" { emit Reject(order) }
    else { g = Gate(order)  if limits not contains "BREACH" and g >= 0 { emit Ticket(order) } }
}'''
    p = al.compile(src, "guard")
    bad = [c["agent"] for c in p.run(order="BUY 15 lots").calls]
    good = [c["agent"] for c in p.run(order="BUY 2 lots").calls]
    assert bad == ["Limits", "Reject"]                     # no model asked once a hard limit is breached
    assert good == ["Limits", "Gate", "Ticket"]
    assert "E103" in codes('agent A(x: text) -> text { goal "g {x}" }\nflow main(x: text) { if y contains "a" { emit x } }')


def test_cached_calls_keep_tool_results_for_guards_and_traces(tmp_path):
    """A cache hit must not lose tool output: guards read it and traces record it (regression, v0.3)."""
    rt.register_tool("limits.cached", "test limits")(lambda q: "BREACH: over limit")
    src = '''tool limits.cached
agent Limits(order: text) -> text { goal "Check {order}" uses limits.cached  policy { cache } }
flow main(order: text) { limits = Limits(order)  emit limits }'''
    p = al.compile(src, "cached_guard")
    traces = []
    for i in range(2):                                          # second run is served from the cache
        r = p.run(order="BUY 15 lots", audit_dir=str(tmp_path), trace=str(tmp_path / f"t{i}.trace.json"))
        traces.append(json.loads(Path(r.trace_path).read_text()))
    for t in traces:
        assert [c["tool"] for c in t["calls"][0]["tool_calls"]] == ["limits.cached"]
        assert "BREACH" in t["calls"][0]["tool_calls"][0]["text"]
