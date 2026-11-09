"""algostream — real-time event processing for AlgoLang (v0.3.1; AlgoPulse™ since v0.3.4).

A `stream` block binds a flow to a topic on an AlgoPulse bus, AlgoLang's built-in event engine
(algopulse.py). Every event that arrives runs the flow once, under the same policies, budgets, human
review and audit log as any other run:

    stream order_flow on main {
        from pulse "market" topic "orders.intent" group "quantoracle-risk-gate"
        map order = event.order
        key event.order_id
        to topic "orders.decisions"
        escalate to topic "orders.review"
        dead letter topic "orders.dlq"
        max in flight 8
    }

    algo stream program.algo --input events.jsonl     offline: events from a file, results to runs/streams/
    algo stream program.algo --pulse                  the bus named in the stream block (algo.config.json)
    algo stream program.algo --pulse --produce events.jsonl   publish sample events to the source topic

Routing of each result
    ok          → `to topic`
    escalated   → `escalate to topic` (a person must decide; the item is also in the review queue)
    blocked, failed, or an event that cannot be read → `dead letter topic`
A route that is not declared falls back to `to topic`. Nothing is ever silently dropped.

Delivery is at-least-once: the consumer group's offset is committed only after the results of a batch
are written. Events with a key already processed in this session are skipped, and the result cache
makes a re-delivered event cheap, so a restart does not double-charge the budget.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

GREEN, RED, GOLD, DIM, END = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    GREEN = RED = GOLD = DIM = END = ""


# ───────────────────────────── messages and brokers ─────────────────────────────
@dataclass
class Message:
    value: bytes | str
    key: str | None = None
    topic: str = ""
    partition: int = 0
    offset: int = 0


class MemoryBroker:
    """In-process broker for development, tests and CI. Topics are lists; output topics are also
    written as JSON Lines under `out_dir` so you can inspect them."""

    def __init__(self, out_dir=None):
        self.topics: dict[str, list[Message]] = {}
        self.pos: dict[str, int] = {}
        self.out_dir = Path(out_dir) if out_dir else None
        self.committed = 0

    def load(self, topic, path):
        """Append every line of a JSON Lines file (or a .json list) to `topic`."""
        text = Path(path).read_text(encoding="utf-8")
        lines = json.loads(text) if path.endswith(".json") else [ln for ln in text.splitlines() if ln.strip()]
        for ln in lines:
            self.produce(topic, ln if isinstance(ln, str) else json.dumps(ln))
        return len(lines)

    def produce(self, topic, value, key=None):
        msgs = self.topics.setdefault(topic, [])
        msgs.append(Message(value, key, topic, 0, len(msgs)))
        if self.out_dir and topic in getattr(self, "_outputs", ()):
            self.out_dir.mkdir(parents=True, exist_ok=True)
            with open(self.out_dir / f"{topic}.jsonl", "a", encoding="utf-8") as fh:
                fh.write((value if isinstance(value, str) else value.decode()) + "\n")

    def subscribe(self, topic, group=None, outputs=()):
        self.source = topic
        self._outputs = set(outputs)
        self.pos.setdefault(topic, 0)

    def poll(self, max_records, timeout=0.0):
        msgs = self.topics.get(self.source, [])
        i = self.pos[self.source]
        batch = msgs[i:i + max_records]
        self.pos[self.source] = i + len(batch)
        return batch

    def flush(self):
        pass

    def commit(self):
        self.committed = self.pos.get(self.source, 0)

    def close(self):
        pass

    def read(self, topic):
        """All messages on a topic, decoded from JSON where possible (handy in tests)."""
        out = []
        for m in self.topics.get(topic, []):
            try:
                out.append(json.loads(m.value))
            except (TypeError, ValueError):
                out.append(m.value)
        return out


class PulseBroker:
    """An AlgoPulse™ bus (algopulse.py): a local folder, or a bus served by `algo pulse serve`.

    The consumer group's committed offset is where reading starts; it moves forward only on commit(),
    which the processor calls after the batch's results have been written. A crash before that point
    means the batch is read again (at-least-once)."""

    def __init__(self, settings: dict):
        import algopulse
        self.settings = settings
        self.bus = algopulse.open_bus(settings)
        self.source = self.group = None
        self.cursor = 0

    def subscribe(self, topic, group=None, outputs=()):
        self.source, self.group = topic, group or "default"
        self.cursor = self.bus.committed(topic, self.group)

    def poll(self, max_records, timeout=1.0):
        deadline = time.time() + timeout
        while True:
            got = self.bus.read(self.source, self.cursor, max_records)
            if got or time.time() >= deadline:
                break
            time.sleep(0.1)
        self.cursor += len(got)
        return [Message(e["value"], e.get("key"), self.source, 0, e["offset"]) for e in got]

    def produce(self, topic, value, key=None):
        self.bus.append(topic, [(key, value)])

    def flush(self):
        pass                                   # every append is already written and fsync'd

    def commit(self):
        if self.source:
            self.bus.commit(self.source, self.group, self.cursor)

    def close(self):
        pass


# ───────────────────────────── the stream processor ─────────────────────────────
def _path(event, path):
    """Read `event.a.b` from a decoded event. Returns (found, value)."""
    cur = event
    for part in path.split(".")[1:]:
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False, None
    return True, cur


def _text(v):
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


@dataclass
class Stats:
    received: int = 0
    ok: int = 0
    escalated: int = 0
    dead_letter: int = 0
    duplicates: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    energy_wh: float = 0.0
    latencies: list = field(default_factory=list)
    started: float = field(default_factory=time.time)

    def to_dict(self):
        lat = sorted(self.latencies)
        pct = (lambda q: round(lat[min(len(lat) - 1, int(q * len(lat)))], 1) if lat else 0.0)
        secs = max(time.time() - self.started, 1e-9)
        return dict(received=self.received, ok=self.ok, escalated=self.escalated, dead_letter=self.dead_letter,
                    duplicates=self.duplicates, tokens=self.tokens, cost_usd=round(self.cost_usd, 6),
                    energy_wh=round(self.energy_wh, 4), latency_p50_ms=pct(0.5), latency_p95_ms=pct(0.95),
                    events_per_second=round(self.received / secs, 2), seconds=round(secs, 2))


class StreamProcessor:
    """Runs one `stream` block of a compiled Program against a broker."""

    def __init__(self, program, stream, broker, live=False, audit_dir=None, dedupe=10_000, log=print):
        self.program, self.st, self.broker = program, stream, broker
        self.live, self.audit_dir, self.log = live, audit_dir, log
        self.stats = Stats()
        self.seen: OrderedDict[str, None] = OrderedDict()
        self.dedupe = dedupe
        self.inputs = program.flow_inputs(stream.flow)
        self._stop = False

    # one event
    def decode(self, msg):
        raw = msg.value.decode("utf-8", "replace") if isinstance(msg.value, bytes) else str(msg.value)
        try:
            return raw, json.loads(raw)
        except ValueError:
            return raw, raw                    # plain-text events are allowed for one-input flows

    def inputs_for(self, event):
        vals, missing = {}, []
        for name in self.inputs:
            path = self.st.mapping.get(name)
            if path is None:
                if isinstance(event, dict) and name in event:
                    vals[name] = _text(event[name])
                elif not isinstance(event, dict) and len(self.inputs) == 1:
                    vals[name] = _text(event)
                else:
                    missing.append(name)
            elif path == "event":
                vals[name] = _text(event)
            else:
                found, v = _path(event, path)
                if found:
                    vals[name] = _text(v)
                else:
                    missing.append(f"{name} (from {path})")
        return vals, missing

    def key_for(self, msg, event):
        if self.st.key:
            if self.st.key == "event":
                return _text(event)
            found, v = _path(event, self.st.key)
            if found:
                return _text(v)
        return msg.key

    def handle(self, msg):
        t0 = time.time()
        raw, event = self.decode(msg)
        key = self.key_for(msg, event)
        base = dict(stream=self.st.name, key=key, source=dict(topic=msg.topic, partition=msg.partition,
                                                              offset=msg.offset),
                    at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
        vals, missing = self.inputs_for(event)
        if missing:
            why = ("event is not a JSON object; needs " if not isinstance(event, dict) else "event is missing ")
            return dict(base, status="invalid", problem=why + ", ".join(missing), event=raw,
                        latency_ms=round((time.time() - t0) * 1000, 1))
        res = self.program.run(live=self.live, quiet=True, audit_dir=self.audit_dir, flow=self.st.flow, **vals)
        d = res.to_dict()
        confs = [c["confidence"] for c in res.calls if c.get("confidence") is not None]
        status = res.status if res.status != "ok" else ("escalated" if res.escalated else "ok")
        return dict(base, status=status, problem=res.problem, inputs=vals, outputs=d["values"],
                    confidence=round(min(confs), 3) if confs else None,
                    escalated=[c["agent"] for c in res.escalated], run_id=res.run_id, audit=res.audit_path,
                    tokens=res.stats.get("tokens", 0), cost_usd=res.stats.get("cost_usd", 0.0),
                    energy_wh=res.stats.get("energy_wh", 0.0), latency_ms=round((time.time() - t0) * 1000, 1))

    def route(self, result):
        st = result["status"]
        if st == "ok":
            return self.st.sink, "ok"
        if st == "escalated":
            return self.st.escalate or self.st.sink, "escalated"
        return self.st.dead_letter or self.st.sink, "dead_letter"

    # the loop
    def process_batch(self, batch):
        todo = []
        for m in batch:
            self.stats.received += 1
            _, event = self.decode(m)
            k = self.key_for(m, event)
            if k is not None and k in self.seen:
                self.stats.duplicates += 1
                continue
            if k is not None:
                self.seen[k] = None
                while len(self.seen) > self.dedupe:
                    self.seen.popitem(last=False)
            todo.append(m)
        workers = max(1, min(self.st.max_in_flight, len(todo)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(self.handle, todo))       # results keep the order of the events
        for r in results:
            topic, bucket = self.route(r)
            setattr(self.stats, bucket, getattr(self.stats, bucket) + 1)
            self.stats.tokens += r.get("tokens", 0) or 0
            self.stats.cost_usd += r.get("cost_usd", 0.0) or 0.0
            self.stats.energy_wh += r.get("energy_wh", 0.0) or 0.0
            self.stats.latencies.append(r["latency_ms"])
            if topic:
                self.broker.produce(topic, json.dumps(r, ensure_ascii=False, default=str), key=r.get("key"))
            mark = {"ok": f"{GREEN}✓{END}", "escalated": f"{GOLD}⚑{END}"}.get(bucket, f"{RED}✗{END}")
            self.log(f"  {mark} {str(r.get('key') or '-')[:24]:<24} {r['status']:<10} → {topic or '(no topic)'}"
                     f"  {DIM}{r['latency_ms']} ms{END}" + (f"  {DIM}{r['problem']}{END}" if r.get("problem") else ""))
        self.broker.flush()
        self.broker.commit()                                  # at-least-once: commit only after results are flushed
        return results

    def run(self, max_events=None, idle=None, batch_size=None):
        """Poll until `max_events` are handled, nothing arrives for `idle` seconds, or Ctrl-C."""
        outputs = [t for t in (self.st.sink, self.st.escalate, self.st.dead_letter) if t]
        self.broker.subscribe(self.st.source, self.st.group, outputs)
        prev = signal.getsignal(signal.SIGINT) if hasattr(signal, "SIGINT") else None
        try:
            signal.signal(signal.SIGINT, lambda *_: setattr(self, "_stop", True))
        except ValueError:                                     # not in the main thread (tests, notebooks)
            prev = None
        last = time.time()
        size = batch_size or max(self.st.max_in_flight, 1)
        try:
            while not self._stop:
                if max_events is not None:
                    size = min(size, max_events - self.stats.received)
                    if size <= 0:
                        break
                batch = self.broker.poll(size, timeout=0.5)
                if not batch:
                    if idle is not None and time.time() - last >= idle:
                        break
                    if isinstance(self.broker, MemoryBroker):
                        break                                 # an offline topic does not grow on its own
                    continue
                last = time.time()
                self.process_batch(batch)
        finally:
            if prev is not None:
                signal.signal(signal.SIGINT, prev)
        return self.stats.to_dict()


# ───────────────────────────── CLI ─────────────────────────────
def pick_stream(program, name=None):
    streams = program._prog.streams
    if not streams:
        raise SystemExit(f"{program.name}.algo has no stream block. Add one, for example:\n"
                         '  stream events on main { from pulse "local" topic "events.in"  to topic "events.out" }')
    if name is None:
        if len(streams) > 1:
            raise SystemExit("this program has several streams; choose one with --name: "
                             + ", ".join(s.name for s in streams))
        return streams[0]
    for s in streams:
        if s.name == name:
            return s
    raise SystemExit(f"no stream named '{name}' (streams: {', '.join(s.name for s in streams)})")


def cli(file, name=None, input_path=None, pulse=False, produce=None, max_events=None, idle=None, live=False,
        as_json=False, out_dir=None):
    import algolang as al
    from algoc import CompileError
    try:
        program = al.load(file)
    except CompileError as e:
        for d in e.diags:
            print(f"  {d}", file=sys.stderr)
        return 1
    st = pick_stream(program, name)
    log = (lambda *_: None) if as_json else print
    out = Path(out_dir) if out_dir else Path("runs") / "streams" / st.name
    if pulse:
        import algopulse
        settings = algopulse.bus_config(st.bus)
        broker = PulseBroker(settings)
        if produce:
            mem = MemoryBroker()
            n = mem.load(st.source, produce)
            helper = StreamProcessor(program, st, mem)
            evs = []
            for m in mem.topics.get(st.source, []):
                _, ev = helper.decode(m)
                evs.append((helper.key_for(m, ev), m.value))
            broker.bus.append(st.source, evs)
            print(f"published {n} event(s) to {st.source} on AlgoPulse bus '{st.bus}' ({algopulse.where(settings)})")
            return 0
        where = f"AlgoPulse bus '{st.bus}' ({algopulse.where(settings)})"
    else:
        if not input_path:
            raise SystemExit("offline mode needs events: --input events.jsonl (or use --pulse for a live AlgoPulse bus)")
        broker = MemoryBroker(out)
        broker.load(st.source, input_path)
        where = f"offline broker, events from {input_path}"
    log(f"{GOLD}▶ stream {st.name}{END}: {st.source} → flow {st.flow} → "
        f"{st.sink or '-'} / {st.escalate or '-'} / {st.dead_letter or '-'}   {DIM}({where}){END}")
    proc = StreamProcessor(program, st, broker, live=live, log=log)
    try:
        summary = proc.run(max_events=max_events, idle=idle)
    finally:
        broker.close()
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(dict(summary, stream=st.name, program=program.name), indent=2))
    if as_json:
        print(json.dumps(dict(summary, stream=st.name), indent=2))
    else:
        s = summary
        log(f"\n  {s['received']} events · {GREEN}{s['ok']} ok{END} · {GOLD}{s['escalated']} escalated{END} · "
            f"{RED}{s['dead_letter']} dead-letter{END} · {s['duplicates']} duplicate(s) skipped")
        log(f"  latency p50 {s['latency_p50_ms']} ms · p95 {s['latency_p95_ms']} ms · {s['events_per_second']} events/s"
            f" · {s['tokens']} tokens · ${s['cost_usd']:.4f} · {s['energy_wh']} Wh")
        if not pulse:
            log(f"  {DIM}results → {out}/<topic>.jsonl · metrics → {out}/metrics.json{END}")
    return 0
