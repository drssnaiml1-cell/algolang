"""Runtime: policies, org config, cache, tools, concurrency."""
import json
import threading
import time

import pytest

import algolang as al
import algoruntime as rt

PROG = '''
tool calc.eval
agent Calc(q: text) -> text {
    role "Calculator"
    goal "Compute {q}"
    uses calc.eval
}
agent Judge(q: text) -> score {
    role "Judge"
    goal "Score {q}"
    policy { require human when confidence < 0.99 }
}
flow main(q: text) {
    a = Calc(q)
    s = Judge(a)
    emit a, s
}
'''


def test_run_is_deterministic_offline():
    p = al.compile(PROG, "det")
    a, b = p.run(q="2+3*4"), p.run(q="2+3*4")
    assert a.ok and b.ok
    assert [rt.Runtime.value(v) for v in a.values] == [rt.Runtime.value(v) for v in b.values]


def test_tool_is_executed_and_recorded():
    r = al.compile(PROG, "tools").run(q="2+3*4")
    calc = [c for c in r.calls if c["agent"] == "Calc"][0]
    assert any(t["tool"] == "calc.eval" for t in calc["tool_calls"])


def test_low_confidence_escalates_to_review_queue():
    r = al.compile(PROG, "esc").run(q="1+1")
    assert r.escalated
    assert al.review.pending()


def test_org_forbid_blocks_at_runtime():
    al.configure(policy={"forbid": ["salary"]})
    src = 'agent A(salary: text) -> text { role "r" goal "g {salary}" }\nflow main(salary: text) { y = A(salary) emit y }'
    with pytest.raises(al.CompileError):           # org config is enforced by the compiler too
        al.compile(src, "forbid")


def test_org_allowed_tools_checked_at_compile_time():
    al.configure(policy={"allowed_tools": ["kb.search"]})
    with pytest.raises(al.CompileError) as e:
        al.compile(PROG, "allowed")
    assert any(d.code == "E115" for d in e.value.diags)


def test_org_allowed_tools_enforced_at_runtime_too():
    p = al.compile(PROG, "allowed_rt")                 # compiled before the policy changed
    al.configure(policy={"allowed_tools": ["kb.search"]})
    r = p.run(q="1+1")
    assert r.status == "blocked" and "calc.eval" in r.problem


def test_stricter_rule_wins():
    al.configure(policy={"max_budget_tokens": 500, "min_human_below": 0.95})
    src = ('agent A(x: text) -> text { role "r" goal "g {x}" policy { budget tokens 9000 '
           'require human when confidence < 0.5 } }\nflow main(x: text) { y = A(x) emit y }')
    r = al.compile(src, "strict").run(x="hello")
    pol = r.calls[0]["policy"]
    assert pol["budget_tokens"] == 500
    assert pol["human_below"] == 0.95


def test_cache_serves_repeat_calls_for_free():
    al.configure(cache={"enabled": True})
    p = al.compile(PROG, "cache")
    first, second = p.run(q="7*6"), p.run(q="7*6")
    assert any(c.get("cached") for c in second.calls)
    assert second.stats["tokens"] < first.stats["tokens"]


def test_custom_tool_registration():
    @al.tool("test.lookup", "test tool")
    def lookup(q):
        return "FOUND-IT"

    src = ('tool test.lookup\nagent A(x: text) -> text { role "r" goal "find {x}" uses test.lookup }\n'
           'flow main(x: text) { y = A(x) emit y }')
    r = al.compile(src, "custom").run(x="anything")
    assert "FOUND-IT" in str(rt.Runtime.value(r.values[0]))


def test_ungranted_tool_is_refused_by_live_loop():
    """A model asking for a tool the agent did not declare must be refused."""
    class Block:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class FakeMessages:
        def __init__(self):
            self.n = 0

        def create(self, **kw):
            self.n += 1
            if self.n == 1:
                return Block(stop_reason="tool_use", usage=Block(input_tokens=5, output_tokens=5),
                             content=[Block(type="tool_use", id="t1", name="file.read", input={"query": "x"})])
            return Block(stop_reason="end_turn", usage=Block(input_tokens=5, output_tokens=5),
                         content=[Block(type="text", text="done\nCONFIDENCE: 0.9")])

    client = Block(messages=FakeMessages())
    backend = rt.ClaudeBackend(client=client)
    r = al.compile(PROG, "live").run(q="1+1", backend=backend)
    calc = [c for c in r.calls if c["agent"] == "Calc"][0]
    attempt = [t for t in calc["tool_calls"] if t["tool"] == "file.read"]
    assert attempt and attempt[0].get("refused") is True


def test_concurrency_limit_is_global():
    al.configure(max_concurrency=2)
    active, peak, lock = [0], [0], threading.Lock()
    orig = rt.MockBackend.complete

    def slow(self, *a, **k):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.02)
        try:
            return orig(self, *a, **k)
        finally:
            with lock:
                active[0] -= 1

    rt.MockBackend.complete = slow
    try:
        al.compile(PROG, "conc").run_batch([{"q": str(i)} for i in range(12)], workers=8)
    finally:
        rt.MockBackend.complete = orig
    assert peak[0] <= 2


def test_config_file_is_loaded(project):
    (project / "algo.config.json").write_text(json.dumps({"policy": {"forbid": ["religion"]}}))
    rt.load_config(reload=True)
    assert "religion" in rt.load_config()["policy"]["forbid"]


def test_without_threads_results_are_identical(monkeypatch):
    """The web playground runs on WebAssembly Python, which has no threads."""
    src = ('agent A(x: text) -> text { role "r" goal "a {x}" }\nagent B(x: text) -> text { role "r" goal "b {x}" }\n'
           'agent Plan(x: text) -> list { role "r" goal "list parts of {x}" }\n'
           'flow main(x: text) { [p, q] = par { A(x), B(x) }\n  parts = Plan(x)\n  r = par for i in parts { A(i) }\n'
           '  emit p, q, r }')
    prog = al.compile(src, "nothreads")
    threaded = prog.run(x="hello")
    monkeypatch.setattr(rt, "CAN_THREAD", False)
    sequential = prog.run(x="hello")
    def plain(x):  # call ids are random per call; compare values and confidences only
        if isinstance(x, list):
            return [plain(i) for i in x]
        return (x.value, x.confidence) if isinstance(x, rt.Result) else x

    def v(res):
        return [plain(x) for x in res.values]
    assert v(threaded) == v(sequential)
    assert prog.run_batch([{"x": "a"}, {"x": "b"}])[1].ok


def test_cache_works_without_sqlite(monkeypatch, tmp_path):
    """Pyodide (the web playground) ships without sqlite3: the cache must fall back to memory."""
    import builtins
    real_import = builtins.__import__

    def no_sqlite(name, *args, **kwargs):
        if name == "sqlite3":
            raise ImportError("no sqlite3 in this build")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_sqlite)
    c = rt.Cache(tmp_path / "cache.sqlite")
    assert c.memory == {} and c.get("k") is None
    c.put("k", ["a", 1], 0.8)
    assert c.get("k") == (["a", 1], 0.8)
    assert not (tmp_path / "cache.sqlite").exists()
