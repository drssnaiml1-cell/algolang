"""AlgoLang v0.3.1: `stream` blocks and real-time event processing (offline broker, Kafka client, live Kafka)."""
import json
import os
import subprocess
import sys
import types
import uuid

import pytest

import algolang as al
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
    from kafka "local" topic "orders.in" group "desk"
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
    assert (st.name, st.flow, st.cluster, st.source, st.group) == ("orders", "main", "local", "orders.in", "desk")
    assert st.mapping == {"order": "event.payload.order", "account": "event.account"}
    assert (st.key, st.sink, st.escalate, st.dead_letter, st.max_in_flight) == \
        ("event.id", "orders.out", "orders.review", "orders.dlq", 4)


def test_stream_checks_flow_inputs_paths_and_loops():
    base = 'agent A(x: text) -> text { goal "do {x}" }\nflow main(x: text) { emit A(x) }\n'
    assert "E122" in codes(base + 'stream s on nope { from kafka "c" topic "t" }')
    assert "E122" in codes(base + 'stream s { to topic "out" }')                                 # no source
    assert "E122" in codes(base + 'stream s { from kafka "c" topic "t"  map y = event.y }')       # not an input
    assert "E122" in codes(base + 'stream s { from kafka "c" topic "t"  map x = payload.x }')     # not the event
    assert "E122" in codes(base + 'stream s { from kafka "c" topic "t"  to topic "t" }')          # endless loop
    assert "E122" in codes(base + 'stream s { from kafka "c" topic "t"  dead letter topic "t" }')
    assert "E122" in codes(base + 'stream s { from kafka "c" topic "t"  max in flight 0 }')
    assert "E122" in codes(base + 'stream s { from kafka "c" topic "a" }\nstream s { from kafka "c" topic "b" }')
    compile_source(base + 'stream s { from kafka "c" topic "t"  map x = event  key event.id  to topic "o" }', "t.algo")


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
           'stream s { from kafka "c" topic "in"  to topic "out" }')
    broker, _, s = run_offline(src, ["hello world"], tmp_path)
    assert broker.read("out")[0]["inputs"] == {"x": "hello world"}


def test_blocked_runs_go_to_the_dead_letter_topic(tmp_path):
    src = ('agent A(x: text) -> text { goal "Echo {x}"  policy { budget tokens 1 } }\nflow main(x: text) { emit A(x) }\n'
           'stream s { from kafka "c" topic "in"  to topic "out"  dead letter topic "dlq" }')
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


# ───────────────────────────── Kafka client wiring ─────────────────────────────
def test_cluster_config_reads_secrets_from_the_environment(tmp_path, monkeypatch):
    (tmp_path / "algo.config.json").write_text(json.dumps({"kafka": {"prod": {
        "bootstrap_servers": "b1:9093", "security_protocol": "SASL_SSL", "sasl_plain_password_env": "KPASS"}}}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KPASS", "s3cret")
    monkeypatch.delenv("ALGO_KAFKA_BOOTSTRAP", raising=False)
    monkeypatch.delenv("ALGO_CONFIG", raising=False)
    import algoruntime
    monkeypatch.setattr(algoruntime, "_CONFIG", None)      # restored after the test
    cfg = algostream.cluster_config("prod")
    assert cfg == {"bootstrap_servers": "b1:9093", "security_protocol": "SASL_SSL", "sasl_plain_password": "s3cret"}
    with pytest.raises(SystemExit):
        algostream.cluster_config("missing")
    monkeypatch.setenv("ALGO_KAFKA_BOOTSTRAP", "override:9092")
    assert algostream.cluster_config("prod")["bootstrap_servers"] == "override:9092"


def test_kafka_broker_commits_after_flush(monkeypatch, tmp_path):
    log = []

    class TP:
        def __init__(self, topic):
            self.topic, self.partition = topic, 0

    class Rec:
        def __init__(self, v, k, off):
            self.value, self.key, self.offset = v, k, off

    class FakeProducer:
        def __init__(self, **kw):
            log.append(("producer", kw))

        def send(self, topic, value=None, key=None):
            log.append(("send", topic, key))

        def flush(self):
            log.append(("flush",))

        def close(self):
            log.append(("close-producer",))

    class FakeConsumer:
        def __init__(self, topic, **kw):
            log.append(("consumer", topic, kw))
            self.batches = [{TP(topic): [Rec(json.dumps({"id": "k1", "x": "hi"}).encode(), b"k1", 0)]}]

        def poll(self, timeout_ms=0, max_records=1):
            return self.batches.pop(0) if self.batches else {}

        def commit(self):
            log.append(("commit",))

        def close(self):
            log.append(("close-consumer",))

    monkeypatch.setitem(sys.modules, "kafka", types.SimpleNamespace(KafkaProducer=FakeProducer, KafkaConsumer=FakeConsumer))
    src = ('agent A(x: text) -> text { goal "Echo {x}" }\nflow main(x: text) { emit A(x) }\n'
           'stream s { from kafka "c" topic "in" group "g"  key event.id  to topic "out" }')
    prog = al.compile(src, "k", base_dir=tmp_path)
    broker = algostream.KafkaBroker({"bootstrap_servers": "h:9092", "security_protocol": "PLAINTEXT", "unknown": 1})
    proc = algostream.StreamProcessor(prog, algostream.pick_stream(prog), broker, audit_dir=str(tmp_path),
                                      log=lambda *_: None)
    s = proc.run(max_events=1)
    broker.close()
    assert s["received"] == 1
    kinds = [e[0] for e in log]
    assert kinds.index("send") < kinds.index("flush") < kinds.index("commit")
    consumer = next(e for e in log if e[0] == "consumer")
    assert consumer[1] == "in" and consumer[2]["group_id"] == "g" and consumer[2]["enable_auto_commit"] is False
    producer = next(e for e in log if e[0] == "producer")[1]
    assert producer["acks"] == "all" and "unknown" not in producer
    assert ("send", "out", b"k1") in log


# ───────────────────────────── live Kafka (CI service containers) ─────────────────────────────
@pytest.mark.skipif(not os.environ.get("ALGO_KAFKA_TEST"), reason="set ALGO_KAFKA_TEST=1 with a Kafka broker running")
def test_live_kafka_round_trip(tmp_path):
    from kafka import KafkaConsumer
    boot = os.environ.get("ALGO_KAFKA_BOOTSTRAP", "localhost:9092")
    run_id = uuid.uuid4().hex[:8]
    src = ('agent A(x: text) -> text { goal "Echo {x}" }\nflow main(x: text) { emit A(x) }\n'
           f'stream s {{ from kafka "ci" topic "in-{run_id}" group "g-{run_id}"  map x = event.x  key event.id\n'
           f'  to topic "out-{run_id}"  dead letter topic "dlq-{run_id}" }}')
    (tmp_path / "live.algo").write_text(src)
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps({"id": f"e{i}", "x": f"event {i}"}) for i in range(3))
                                           + "\nnot json\n")
    (tmp_path / "algo.config.json").write_text(json.dumps({"kafka": {"ci": {"bootstrap_servers": boot}}}))
    algo = [sys.executable, str(ROOT / "algoc.py"), "stream", "live.algo", "--kafka"]
    env = dict(os.environ, ALGO_AUDIT_DIR=str(tmp_path / "audit"))
    r = subprocess.run(algo + ["--produce", "events.jsonl"], cwd=tmp_path, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(algo + ["--max", "4", "--idle", "60", "--json"], cwd=tmp_path, capture_output=True,
                       text=True, env=env, timeout=180)
    assert r.returncode == 0, r.stderr
    m = json.loads(r.stdout[r.stdout.index("{"):])
    assert m["received"] == 4 and m["dead_letter"] == 1 and m["ok"] + m["escalated"] == 3
    c = KafkaConsumer(f"out-{run_id}", f"dlq-{run_id}", bootstrap_servers=boot, auto_offset_reset="earliest",
                      consumer_timeout_ms=15000)
    got = [json.loads(rec.value) for rec in c]
    c.close()
    assert sorted(g["key"] for g in got if g["status"] != "invalid") == ["e0", "e1", "e2"]
    assert sum(g["status"] == "invalid" for g in got) == 1
