"""AlgoLang v0.4.1: LLM/SLM graph optimisation, SLM-first cascades and the local small-model backend."""
import importlib.util
import json
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import algolang as al
import algoruntime as rt
from conftest import ROOT, write

APP = ROOT / "enterprise-apps" / "llm-graph-optimizer"


@pytest.fixture
def gt():
    spec = importlib.util.spec_from_file_location("graph_tools_test", APP / "plugins" / "graph_tools.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def config(project, **cfg):
    write(project / "algo.config.json", json.dumps(cfg))
    rt._CONFIG = None
    rt.load_config(reload=True)


# ───────────────────────────── the optimiser ─────────────────────────────
def random_dag(rng, n):
    order = [f"a{i}" for i in range(n)]
    preds = {a: {order[j] for j in range(i) if rng.random() < 0.35} for i, a in enumerate(order)}
    options = {a: [(round(rng.uniform(0, 0.01), 6), round(rng.uniform(0.5, 4.0), 2), f"m{k}")
                   for k in range(rng.randint(1, 4))] for a in order}
    return order, preds, options


def test_branch_and_bound_matches_brute_force_on_random_graphs(gt):
    rng = random.Random(7)
    checked = infeasible = 0
    for _ in range(150):
        order, preds, options = random_dag(rng, rng.randint(2, 7))
        limit = rng.uniform(1.0, 12.0)
        got = gt.solve(order, preds, {k: list(v) for k, v in options.items()}, limit)
        want = gt.brute_force(order, preds, options, limit)
        if want is None:
            assert got is None
            infeasible += 1
            continue
        cost, choice, _ = got
        assert abs(cost - want) < 1e-9
        by = {n: {o[2]: o for o in options[n]} for n in order}
        assert gt.critical_path(order, preds, {n: by[n][choice[n]][1] for n in order})[0] <= limit + 1e-9
        checked += 1
    assert checked > 80 and infeasible > 5


def test_parallel_agents_do_not_add_latency(gt):
    order = ["a", "b", "c", "d"]                       # b and c run in parallel after a; d joins them
    preds = {"a": set(), "b": {"a"}, "c": {"a"}, "d": {"b", "c"}}
    assert gt.critical_path(order, preds, {"a": 1, "b": 2, "c": 3, "d": 1})[0] == 5


def test_optimiser_on_a_real_program(gt):
    out = gt.optimise("../claims-ops-center/programs/claims_intake.algo with quality >= 0.8 and latency <= 12 s")
    first = out.splitlines()[0]
    assert first.startswith("VERIFIED") and "brute force" in first and "agrees" in first
    assert "agent_models" in out and "local:" in out and "% lower" in out
    rows = [ln.split(" | ") for ln in out.splitlines() if ln.count(" | ") == 6 and not ln.startswith("agent |")]
    assert rows and all(float(r[4]) >= float(r[2]) for r in rows)          # every agent meets its quality floor
    cloud = gt.optimise("../claims-ops-center/programs/claims_intake.algo latency <= 12 s, cloud only")
    assert "local:" not in cloud and cloud.startswith("VERIFIED")
    tight = gt.optimise("../bank-credit-onboarding/programs/loan_decision.algo latency <= 3 s")
    assert tight.startswith("INFEASIBLE") and "critical path" in tight


def test_optimiser_refuses_paths_outside_the_apps(gt):
    with pytest.raises(ValueError):
        gt.resolve("../../../../etc/passwd.algo")
    assert gt.optimize_tool("no program here").startswith("INFEASIBLE")


def test_analysis_and_triage(gt):
    a = gt.analyse("../claims-ops-center/programs/claims_intake.algo")
    assert "10 agents" in a and "critical path" in a and "triage.Intake" in a
    assert gt.triage("What are your opening hours?").startswith("SIMPLE")
    assert gt.triage("Analyse the contract, plan the negotiation strategy and assess the regulatory risk").startswith("COMPLEX")
    assert gt.triage("Triage this request: Compare the two loans and explain why, with 8.6% and INR 45 lakh and 18 lakh "
                     "income and 2 children; which is better?").startswith("COMPLEX")


# ───────────────────────────── runtime: routing and local models ─────────────────────────────
def test_agent_models_route_an_agent_without_editing_the_program(project):
    config(project, agent_models={"A": "local:phi-4-mini"}, pricing={"local:*": [0, 0], "default": [3, 15]})
    src = 'agent A(x: text) -> text { goal "do {x}" }\nagent B(x: text) -> text { goal "do {x}" }\nflow main(x: text) { emit A(x), B(x) }'
    res = al.compile(src, "p").run(x="1")
    models = {c["agent"]: c["model"] for c in res.calls}
    assert models["A"] == "local:phi-4-mini" and models["B"] != "local:phi-4-mini"
    cost = {c["agent"]: c["cost_usd"] for c in res.calls}
    assert cost["A"] == 0 and cost["B"] > 0


def test_prefix_pricing_and_energy(project):
    cfg = {"pricing": {"local:*": [0, 0], "default": [3, 15]}, "energy": {"wh_per_1k_tokens": {"local:*": 0.02, "default": 0.3}}}
    assert rt.price_usd("local:qwen", 1000, 1000, cfg) == 0
    assert rt.price_usd("claude-x", 1_000_000, 0, cfg) == 3
    assert rt.energy_wh("local:qwen", 1000, cfg) == 0.02


class FakeOpenAI(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOpenAI.seen.append((self.path, self.headers.get("Authorization"), body))
        answer = {"value": "Branches open 10:00-14:00 on Saturday", "confidence": 0.91,
                  "reasons": ["opening hours policy"], "evidence": ["Saturday"]}
        out = {"choices": [{"message": {"role": "assistant", "content": "Sure:\n" + json.dumps(answer)}}],
               "usage": {"prompt_tokens": 42, "completion_tokens": 17}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def fake_server():
    srv = HTTPServer(("127.0.0.1", 0), FakeOpenAI)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    FakeOpenAI.seen = []
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()


def test_local_backend_talks_openai_compatible(project, fake_server, monkeypatch):
    monkeypatch.setenv("LOCAL_KEY", "sk-local")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rt.register_tool("hours.lookup", "Branch hours")(lambda q: "Saturday 10:00-14:00")
    config(project, local_models={"base_url": fake_server, "api_key_env": "LOCAL_KEY"})
    src = ('model slm = "local:phi-4-mini"\ntool hours.lookup\n'
           'agent A(q: text) -> text { goal "Answer {q}"  uses hours.lookup  model slm  policy { explain with evidence } }\n'
           'flow main(q: text) { emit A(q) }')
    res = al.compile(src, "p").run(live=True, q="When are you open on Saturday?")
    assert res.status == "ok" and res.values[0].startswith("Branches open")
    path, auth, body = FakeOpenAI.seen[0]
    assert path == "/v1/chat/completions" and auth == "Bearer sk-local" and body["model"] == "phi-4-mini"
    assert "TOOL RESULTS" in body["messages"][1]["content"] and "Saturday 10:00-14:00" in body["messages"][1]["content"]
    call = res.calls[0]
    assert call["tokens"] == 59 and call["cost_usd"] == 0 and call["explanation"]["grounded"]


def test_live_without_a_claude_key_only_runs_local_models(project, fake_server, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config(project, local_models={"base_url": fake_server})
    src = ('model slm = "local:phi-4-mini"\nmodel llm = "claude-opus-5-5"\n'
           'agent S(q: text) -> text { goal "Answer {q}"  model slm }\nagent L(q: text) -> text { goal "Answer {q}"  model llm }\n'
           'flow main(q: text) { emit S(q), L(q) }')
    res = al.compile(src, "p").run(live=True, q="hi")
    assert res.status == "failed" and "ANTHROPIC_API_KEY" in res.problem
    assert res.calls[0]["agent"] == "S" and res.calls[0]["status"] == "ok"


def test_cascade_program_and_optimiser_program_pass_their_evals(root, project, monkeypatch):
    import algoeval
    monkeypatch.chdir(APP)
    rt._CONFIG = None
    rt.load_config(reload=True)
    for prog in ("cascade_router", "graph_optimizer"):
        results = algoeval.run_evals(al.load(APP / "programs" / f"{prog}.algo"), audit_dir=str(project / prog))
        assert results and all(r["passed"] for r in results), [r["failures"] for r in results]
