"""AlgoLang `stream` blocks and AlgoPulse™, the built-in real-time event engine (local bus, served bus, CI server)."""
import json
import os
import subprocess
import sys
import uuid

import pytest

import algolang as al
import algopulse
import algostream
from algoc import CompileError, compile_source
from conftest import ROOT

DESK = '''
agent Classify(order: text) -> text {
    role "Order desk"
    goal "Classify {order}"
}
agent Escalate(order: text) -> text {
    goal "Prepare {order} for a human"
    policy { require human when confidence < 1.01 }
}
flow main(order: text, account: text = "PAPER") {
    c = Classify(order)
    if c contains "URGENT" {
        emit c, Escalate(order)
    } else {
        emit c
    }
}
stream orders on main {
    from pulse "local" topic "orders.in" group "desk"
    map order = event.payload.order, account = event.account
    key event.id
    to topic "orders.out"
    escalate to topic "orders.review"
    dead letter topic "orders.dlq"
    max in flight 4
}
'''


def codes(src):
    with pytest.raises(CompileError) as e:
        compile_source(src, "t.algo")
    return [d.code for d in e.value.diags]


def events(*items):
    return [it if isinstance(it, str) else json.dumps(it) for it in items]


def run_offline(src, msgs, tmp_path):
    prog = al.compile(src, "desk", base_dir=tmp_path)
    st = algostream.pick_stream(prog)
    broker = algostream.MemoryBroker(tmp_path / "out")
    broker.subscribe(st.source)
    for m in msgs:
        broker.produce(st.source, m)
    proc = algostream.StreamProcessor(prog, st, broker, audit_dir=str(tmp_path / "audit"), log=lambda *_: None)
    return broker, proc, proc.run()


# ───────────────────────────── language ─────────────────────────────
def test_stream_block_parses_into_the_program(tmp_path):
    prog = al.compile(DESK, "desk", base_dir=tmp_path)
    (st,) = prog._prog.streams
    assert (st.name, st.flow, st.bus, st.source, st.group) == ("orders", "main", "local", "orders.in", "desk")
    assert st.mapping == {"order": "event.payload.order", "account": "event.account"}
    assert (st.key, st.sink, st.escalate, st.dead_letter, st.max_in_flight) == \
        ("event.id", "orders.out", "orders.review", "orders.dlq", 4)


def test_stream_checks_flow_inputs_paths_and_loops():
    base = 'agent A(x: text) -> text { goal "do {x}" }\nflow main(x: text) { emit A(x) }\n'
    assert "E122" in codes(base + 'stream s on nope { from pulse "c" topic "t" }')
    assert "E122" in codes(base + 'stream s { to topic "out" }')                                 # no source
    assert "E122" in codes(base + 'stream s { from pulse "c" topic "t"  map y = event.y }')       # not an input
    assert "E122" in codes(base + 'stream s { from pulse "c" topic "t"  map x = payload.x }')     # not the event
    assert "E122" in codes(base + 'stream s { from pulse "c" topic "t"  to topic "t" }')          # endless loop
    assert "E122" in codes(base + 'stream s { from pulse "c" topic "t"  dead letter topic "t" }')
    assert "E122" in codes(base + 'stream s { from pulse "c" topic "t"  max in flight 0 }')
    assert "E122" in codes(base + 'stream s { from pulse "c" topic "a" }\nstream s { from pulse "c" topic "b" }')
    compile_source(base + 'stream s { from pulse "c" topic "t"  map x = event  key event.id  to topic "o" }', "t.algo")


# ───────────────────────────── processing ─────────────────────────────
def test_events_are_routed_by_outcome_and_nothing_is_dropped(tmp_path):
    msgs = events({"id": "o1", "account": "A1", "payload": {"order": "buy 1 lot"}},
                  {"id": "o2", "account": "A2", "payload": {"order": "URGENT sell everything"}},
                  {"id": "o3", "account": "A3"},                                  # missing payload.order
                  "this is not json",
                  {"id": "o1", "account": "A1", "payload": {"order": "buy 1 lot"}})  # re-delivered duplicate
    broker, proc, s = run_offline(DESK.replace('goal "Classify {order}"', 'goal "Classify {order}: say URGENT if it says URGENT"'), msgs, tmp_path)
    total = s["ok"] + s["escalated"] + s["dead_letter"] + s["duplicates"]
    assert s["received"] == 5 and total == 5 and s["duplicates"] == 1 and s["dead_letter"] == 2
    out, review, dlq = broker.read("orders.out"), broker.read("orders.review"), broker.read("orders.dlq")
    assert len(out) + len(review) == 2
    assert {r["key"] for r in out + review} == {"o1", "o2"}
    assert {r["status"] for r in dlq} == {"invalid"}
    assert any("not a JSON object" in r["problem"] for r in dlq)
    assert any("payload.order" in r["problem"] for r in dlq)
    first = (out + review)[0]
    assert first["inputs"]["account"] in ("A1", "A2") and first["run_id"] and first["audit"]
    assert first["source"]["topic"] == "orders.in" and "latency_ms" in first
    assert broker.committed == 5                         # offsets committed only after results were written
    assert (tmp_path / "out" / "orders.dlq.jsonl").exists()
    assert broker.read("orders.in")[:1] == [json.loads(msgs[0])]   # the source topic is never written to


def test_escalated_runs_go_to_the_review_topic(tmp_path):
    src = DESK.replace("if c contains \"URGENT\"", "if c not contains \"zzz-never\"")
    broker, _, s = run_offline(src, events({"id": "e1", "account": "A", "payload": {"order": "x"}}), tmp_path)
    assert s["escalated"] == 1 and broker.read("orders.review")[0]["escalated"] == ["Escalate"]


def test_unrouted_outcomes_fall_back_to_the_main_topic(tmp_path):
    src = DESK.replace('    escalate to topic "orders.review"\n', "").replace('    dead letter topic "orders.dlq"\n', "")
    broker, _, s = run_offline(src, events("broken"), tmp_path)
    assert s["dead_letter"] == 1 and broker.read("orders.out")[0]["status"] == "invalid"


def test_plain_text_events_feed_a_one_input_flow(tmp_path):
    src = ('agent A(x: text) -> text { goal "Echo {x}" }\nflow main(x: text) { emit A(x) }\n'
           'stream s { from pulse "c" topic "in"  to topic "out" }')
    broker, _, s = run_offline(src, ["hello world"], tmp_path)
    assert broker.read("out")[0]["inputs"] == {"x": "hello world"}


def test_blocked_runs_go_to_the_dead_letter_topic(tmp_path):
    src = ('agent A(x: text) -> text { goal "Echo {x}"  policy { budget tokens 1 } }\nflow main(x: text) { emit A(x) }\n'
           'stream s { from pulse "c" topic "in"  to topic "out"  dead letter topic "dlq" }')
    broker, _, s = run_offline(src, ["a long enough input to exceed one token"], tmp_path)
    assert s["dead_letter"] == 1 and broker.read("dlq")[0]["status"] in ("blocked", "failed")


def test_cli_offline_writes_topics_and_metrics(tmp_path):
    app = ROOT / "enterprise-apps" / "algo-trading-desk"
    out = tmp_path / "streams"
    r = subprocess.run([sys.executable, str(ROOT / "algoc.py"), "stream", "programs/pre_trade_check.algo",
                        "--input", "data/order_events.jsonl", "--out", str(out), "--json"],
                       cwd=app, capture_output=True, text=True, env=dict(os.environ, ALGO_AUDIT_DIR=str(tmp_path)))
    assert r.returncode == 0, r.stderr
    m = json.loads(r.stdout[r.stdout.index("{"):])
    assert m["received"] == 6 and m["duplicates"] == 1 and m["dead_letter"] == 2
    assert m["ok"] + m["escalated"] == 3
    assert json.loads((out / "metrics.json").read_text())["stream"] == "order_flow"
    assert (out / "orders.dlq.jsonl").exists()


# ───────────────────────────── AlgoPulse™ event engine ─────────────────────────────
def test_pulse_log_is_durable_and_resumes_from_the_committed_offset(tmp_path):
    log = algopulse.PulseLog(tmp_path / "bus")
    assert log.append("orders.in", [("k1", "a"), ("k2", {"x": 1}), (None, "c")]) == [0, 1, 2]
    assert [e["value"] for e in log.read("orders.in", 1, 5)] == ['{"x": 1}', "c"]
    assert log.committed("orders.in", "desk") == 0
    log.commit("orders.in", "desk", 2)
    again = algopulse.PulseLog(tmp_path / "bus")          # a restart: a fresh process sees the same state
    assert again.committed("orders.in", "desk") == 2 and again.end("orders.in") == 3
    assert again.append("orders.in", [("k4", "d")]) == [3]
    assert log.end("orders.in") == 4                      # the first handle sees the other writer's event
    assert again.topics() == {"orders.in": 4}


def test_pulse_names_cannot_escape_the_bus_folder(tmp_path):
    log = algopulse.PulseLog(tmp_path / "bus")
    for bad in ("../etc", "a/b", "", ".hidden", "x" * 200, "a..b"):
        with pytest.raises(ValueError):
            log.append(bad, [(None, "v")])
    with pytest.raises(ValueError):
        log.commit("ok", "../group", 1)


def test_concurrent_writers_never_lose_or_reuse_an_offset(tmp_path):
    import threading
    logs = [algopulse.PulseLog(tmp_path / "bus") for _ in range(4)]

    def write(i):
        for j in range(25):
            logs[i].append("t", [(f"{i}-{j}", "v")])

    ts = [threading.Thread(target=write, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    got = logs[0].read("t", 0, 1000)
    assert [e["offset"] for e in got] == list(range(100)) and len({e["key"] for e in got}) == 100


def test_stream_on_a_pulse_bus_commits_only_after_results(tmp_path):
    src = ('agent A(x: text) -> text { goal "Echo {x}" }\nflow main(x: text) { emit A(x) }\n'
           'stream s { from pulse "b" topic "in" group "g"  key event.id  to topic "out" }')
    prog = al.compile(src, "p", base_dir=tmp_path)
    settings = {"dir": str(tmp_path / "bus")}
    algopulse.open_bus(settings).append("in", [(None, json.dumps({"id": f"e{i}", "x": f"hi {i}"})) for i in range(3)])
    broker = algostream.PulseBroker(settings)
    proc = algostream.StreamProcessor(prog, algostream.pick_stream(prog), broker, audit_dir=str(tmp_path),
                                      log=lambda *_: None)
    s = proc.run(max_events=2, idle=0.2)
    bus = algopulse.open_bus(settings)
    assert s["received"] == 2 and bus.committed("in", "g") == 2
    assert [json.loads(e["value"])["key"] for e in bus.read("out")] == ["e0", "e1"]
    proc2 = algostream.StreamProcessor(prog, algostream.pick_stream(prog), algostream.PulseBroker(settings),
                                       audit_dir=str(tmp_path), log=lambda *_: None)
    assert proc2.run(idle=0.2)["received"] == 1          # a new run picks up exactly where the group stopped
    assert bus.committed("in", "g") == 3 and bus.end("out") == 3


def test_bus_config_local_folder_and_served_bus(tmp_path, monkeypatch):
    import algoruntime
    (tmp_path / "algo.config.json").write_text(json.dumps({"pulse": {
        "edge": {"url": "http://10.0.0.5:7070", "token_env": "EDGE_TOKEN"}, "near": {"dir": "data/near"}}}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ALGO_CONFIG", raising=False)
    monkeypatch.delenv("ALGO_PULSE_URL", raising=False)
    monkeypatch.setattr(algoruntime, "_CONFIG", None)
    monkeypatch.setenv("EDGE_TOKEN", "s3cret")
    assert algopulse.bus_config("edge") == {"url": "http://10.0.0.5:7070", "token": "s3cret"}
    assert algopulse.bus_config("near")["dir"].endswith(os.path.join("data", "near"))
    assert algopulse.bus_config("other")["dir"].endswith(os.path.join("pulse", "other"))
    monkeypatch.setenv("ALGO_PULSE_URL", "http://hub:7070")
    assert algopulse.bus_config("near")["url"] == "http://hub:7070"


def test_served_bus_requires_the_token_and_round_trips(tmp_path):
    import threading
    srv = algopulse.make_server(tmp_path / "bus", port=0, token="t0ken", quiet=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}"
    try:
        with pytest.raises(RuntimeError, match="401"):
            algopulse.PulseClient(url, "wrong").topics()
        c = algopulse.PulseClient(url, "t0ken")
        assert c.append("orders.in", [("a", "one"), ("b", "two")]) == [0, 1]
        assert [e["key"] for e in c.read("orders.in", 0, 10)] == ["a", "b"]
        c.commit("orders.in", "g", 1)
        assert c.committed("orders.in", "g") == 1 and c.topics() == {"orders.in": 2}
        with pytest.raises(RuntimeError, match="400"):
            c._call("GET", "/topics/..%2Fsecret/events")
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.skipif(not os.environ.get("ALGO_PULSE_TEST_URL"), reason="set ALGO_PULSE_TEST_URL to a running `algo pulse serve`")
def test_live_pulse_server_round_trip(tmp_path):
    url, run_id = os.environ["ALGO_PULSE_TEST_URL"], uuid.uuid4().hex[:8]
    src = ('agent A(x: text) -> text { goal "Echo {x}" }\nflow main(x: text) { emit A(x) }\n'
           f'stream s {{ from pulse "ci" topic "in-{run_id}" group "g-{run_id}"  map x = event.x  key event.id\n'
           f'  to topic "out-{run_id}"  dead letter topic "dlq-{run_id}" }}')
    (tmp_path / "live.algo").write_text(src)
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps({"id": f"e{i}", "x": f"event {i}"}) for i in range(3))
                                           + "\nnot json\n")
    (tmp_path / "algo.config.json").write_text(json.dumps({"pulse": {"ci": {"url": url}}}))
    algo = [sys.executable, str(ROOT / "algoc.py"), "stream", "live.algo", "--pulse"]
    env = dict(os.environ, ALGO_AUDIT_DIR=str(tmp_path / "audit"))
    r = subprocess.run(algo + ["--produce", "events.jsonl"], cwd=tmp_path, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(algo + ["--max", "4", "--idle", "20", "--json"], cwd=tmp_path, capture_output=True,
                       text=True, env=env, timeout=180)
    assert r.returncode == 0, r.stderr
    m = json.loads(r.stdout[r.stdout.index("{"):])
    assert m["received"] == 4 and m["dead_letter"] == 1 and m["ok"] + m["escalated"] == 3
    c = algopulse.PulseClient(url, os.environ.get("ALGO_PULSE_TOKEN"))
    got = [json.loads(e["value"]) for e in c.read(f"out-{run_id}", 0, 10) + c.read(f"dlq-{run_id}", 0, 10)]
    assert sorted(g["key"] for g in got if g["status"] != "invalid") == ["e0", "e1", "e2"]
    assert c.committed(f"in-{run_id}", f"g-{run_id}") == 4
