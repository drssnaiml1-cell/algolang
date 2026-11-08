"""
algoruntime — execution engine for compiled AlgoLang programs (v0.3)
AlgoProfessor AI R&D Solutions

Every call in an AlgoLang program is an agent call. For each call the runtime:
  • renders the agent's role + goal into a prompt
  • applies the agent's policy *and* the organisation's policy (algo.config.json)
  • enforces forbidden attributes, token budgets, a run-level token cap, retries,
    timeouts and the human-in-the-loop gate
  • executes the agent's granted tools (built-in or registered by your company)
  • reuses cached results when caching is on
  • limits how many model calls run at once across the whole process
  • writes a hash-chained (tamper-evident) audit record
  • puts low-confidence results in a review queue for people to approve or reject
  • samples uncertain<T> agents several times and turns their agreement into confidence   (v0.3)
  • prices every call in money (USD/INR) and energy (Wh, g CO₂) and enforces cost/energy budgets (v0.3)
  • records traces that `algo replay` re-runs with no model calls                          (v0.3)
  • binds tools to MCP servers (`tool x from mcp "server"`)                                (v0.3)

Backends
  mock  (default)  deterministic, offline — for teaching, tests and CI
  live  (ALGO_LIVE=1 + ANTHROPIC_API_KEY)  calls Claude via the anthropic SDK
  replay (algo replay / eval --replay)    answers from a recorded trace — zero tokens, zero cost
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import importlib.util
import json
import operator
import os
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

VERSION = "0.3.2"
# WebAssembly builds of Python (Pyodide, used by the web playground) cannot start threads:
# `par` then runs its branches one after another, with identical results.
CAN_THREAD = sys.platform not in ("emscripten", "wasi")


class PolicyViolation(Exception):
    pass


class ReplayMiss(Exception):
    """Replay found an agent call whose inputs are not in the recorded trace (the program changed)."""


@dataclass
class AgentSpec:
    name: str
    params: list
    returns: str
    role: str = ""
    goal: str = ""
    uses: list = field(default_factory=list)
    model: str | None = None
    policy: dict = field(default_factory=dict)


@dataclass
class Result:
    """What every agent returns: a value plus its provenance."""
    value: object
    confidence: float
    agent: str
    call_id: str
    status: str = "ok"           # ok | escalated | approved
    samples: list | None = None  # uncertain<T>: every sampled value
    spread: float | None = None  # uncertain<T>: disagreement between samples (0 = all agree)
    tool_text: str = ""          # full text the agent's tools returned (searched by `contains` guards)

    def __str__(self):
        return str(self.value)


def base_type(t: str) -> str:
    return t[10:-1] if t.startswith("uncertain<") else t


def _stdev(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def _jsonable(v):
    if isinstance(v, Result):
        v = v.value
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    return v if isinstance(v, (str, int, float, bool, type(None))) else str(v)


# ═════════════════════════ organisation configuration ═════════════════════════
DEFAULT_CONFIG = {
    "organisation": "",
    "policy": {                      # applied on top of every agent's own policy; stricter wins
        "forbid": [],                # protected attributes no agent may receive
        "max_budget_tokens": None,   # cap on any agent's token budget
        "min_human_below": None,     # every agent sends results below this confidence to people
        "allowed_tools": None,       # list → only these tools may be used by any agent
    },
    "max_concurrency": 16,           # model calls running at once, across all flows and batch rows
    "max_run_tokens": None,          # stop a single run that would use more tokens than this
    "cache": {"enabled": False, "path": None},      # None → <audit_dir>/cache.sqlite
    "audit_dir": "runs",
    "review_queue": None,                           # None → <audit_dir>/review_queue.jsonl
    "models": {},                    # central model governance: short name → model id override
    "tools": {"file.read": {"root": "."}, "kb.search": {"dir": "kb"}},
    "plugins": [],                   # Python files that register company tools
    # ── v0.3: money and energy ──
    # USD per million tokens [input, output]. These are placeholders — set your organisation's contracted prices.
    "pricing": {"default": [3.0, 15.0], "claude-haiku-5-5": [1.0, 5.0], "claude-sonnet-5-5": [3.0, 15.0],
                "claude-opus-5-5": [5.0, 25.0]},
    "usd_to_inr": 84.0,
    # Rough inference-energy estimates (Wh per 1,000 tokens) and grid carbon intensity (kg CO₂ per kWh, India ≈ 0.71).
    "energy": {"wh_per_1k_tokens": {"default": 0.3, "claude-haiku-5-5": 0.1, "claude-sonnet-5-5": 0.3,
                                    "claude-opus-5-5": 0.6},
               "grid_kg_co2_per_kwh": 0.71},
    "estimate_output_tokens": 500,   # used to price a call before it runs (pre-flight budget checks)
    "max_run_cost_usd": None,        # stop a run that would cost more than this
    "max_run_energy_wh": None,       # stop a run that would use more energy than this
    # ── v0.3: MCP servers that `tool x from mcp "name"` can use ──
    #   {"company-kb": {"command": "{python}", "args": ["mcp_demo_server.py"]},
    #    "remote":     {"url": "https://example.com/mcp", "headers": {"Authorization": "Bearer …"}}}
    "mcp_servers": {},
    # quantum.* tools (v0.3.2): backend "simulator" (built in) or "qiskit-aer"; the stricter of max_qubits and an
    # agent's `max qubits` applies; seed makes every quantum answer reproducible for audit and replay
    "quantum": {"backend": "simulator", "max_qubits": 20, "shots": 1024, "seed": 7, "qaoa_layers": 2},
}

_CONFIG = None
_CONFIG_LOCK = threading.Lock()


def _deep_merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def config_path():
    p = os.environ.get("ALGO_CONFIG")
    if p:
        return Path(p)
    here = Path.cwd() / "algo.config.json"
    return here if here.exists() else None


def load_config(reload=False):
    """Organisation configuration from ALGO_CONFIG or ./algo.config.json (merged over defaults)."""
    global _CONFIG
    with _CONFIG_LOCK:
        if _CONFIG is None or reload:
            cfg = dict(DEFAULT_CONFIG)
            p = config_path()
            if p and p.exists():
                cfg = _deep_merge(cfg, json.loads(p.read_text(encoding="utf-8")))
            _CONFIG = cfg
            for plugin in cfg.get("plugins") or []:
                _load_plugin(plugin)
        return _CONFIG


def configure(**overrides):
    """Override configuration in code (used by the SDK)."""
    global _CONFIG
    cfg = load_config()
    with _CONFIG_LOCK:
        _CONFIG = _deep_merge(cfg, overrides)
        _SEMAPHORE_SIZE[0] = None
    return _CONFIG


def price_usd(model, tokens_in, tokens_out, cfg=None):
    """Money for one model call, from the `pricing` table in algo.config.json."""
    table = (cfg or load_config()).get("pricing") or {}
    p_in, p_out = table.get(model) or table.get("default") or [0, 0]
    return (tokens_in * p_in + tokens_out * p_out) / 1_000_000


def energy_wh(model, tokens, cfg=None):
    """Estimated inference energy for one call, from the `energy` table in algo.config.json."""
    rates = ((cfg or load_config()).get("energy") or {}).get("wh_per_1k_tokens") or {}
    return tokens / 1000 * float(rates.get(model, rates.get("default", 0.3)))


def co2_grams(wh, cfg=None):
    k = float(((cfg or load_config()).get("energy") or {}).get("grid_kg_co2_per_kwh", 0.71))
    return wh * k          # Wh × kg/kWh = g


_SEMAPHORE = [None]
_SEMAPHORE_SIZE = [None]


def _semaphore():
    n = int(load_config().get("max_concurrency") or 16)
    with _CONFIG_LOCK:
        if _SEMAPHORE_SIZE[0] != n:
            _SEMAPHORE[0] = threading.BoundedSemaphore(n)
            _SEMAPHORE_SIZE[0] = n
        return _SEMAPHORE[0]


# ═════════════════════════════════ tools ═════════════════════════════════════
@dataclass
class Tool:
    name: str
    fn: object
    description: str = ""
    schema: dict | None = None       # JSON schema of the arguments (MCP tools); None → one "query" string


TOOLS: dict[str, Tool] = {}


def register_tool(name, description=""):
    """Decorator: make a Python function available to agents that `uses` this tool.

        @register_tool("crm.lookup", "Look up a customer record by name or ID")
        def crm_lookup(query: str) -> str: ...
    """
    def deco(fn):
        TOOLS[name] = Tool(name, fn, description or (fn.__doc__ or "").strip())
        return fn
    return deco


def _load_plugin(path):
    p = Path(path)
    if not p.is_absolute():
        base = config_path().parent if config_path() else Path.cwd()
        p = base / p
    spec = importlib.util.spec_from_file_location(f"algo_plugin_{p.stem}", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("only arithmetic is allowed")


@register_tool("calc.eval", "Evaluate an arithmetic expression such as (1200 * 0.18) + 45")
def _calc(query: str) -> str:
    m = re.findall(r"[\d\.\s\+\-\*/\(\)%]+", query)
    expr = max(m, key=len).strip() if m else ""
    try:
        return f"{expr} = {_safe_eval(ast.parse(expr, mode='eval'))}"
    except Exception as e:  # noqa
        return f"could not evaluate '{expr}': {e}"


@register_tool("file.read", "Read a text file from the organisation's workspace (path relative to it)")
def _file_read(query: str) -> str:
    root = Path(load_config()["tools"].get("file.read", {}).get("root", ".")).resolve()
    m = re.search(r"[\w\-./\\]+\.(?:txt|md|csv|json|log|algo)", query)
    if not m:
        return "no file name found in the request"
    p = (root / m.group(0)).resolve()
    if not str(p).startswith(str(root)):
        return "refused: path is outside the permitted workspace"
    if not p.exists():
        return f"not found: {m.group(0)}"
    return p.read_text(encoding="utf-8", errors="replace")[:4000]


@register_tool("kb.search", "Search the organisation's knowledge base of .txt and .md documents")
def _kb_search(query: str) -> str:
    kb = Path(load_config()["tools"].get("kb.search", {}).get("dir", "kb"))
    docs = list(kb.rglob("*.txt")) + list(kb.rglob("*.md")) if kb.exists() else []
    if not docs:
        return f"knowledge base '{kb}' is empty"
    terms = {w for w in re.findall(r"[a-z0-9]{3,}", query.lower())}
    scored = []
    for d in docs:
        text = d.read_text(encoding="utf-8", errors="replace")
        for para in re.split(r"\n\s*\n", text):
            words = re.findall(r"[a-z0-9]{3,}", para.lower())
            hits = sum(1 for w in words if w in terms)
            if hits:
                scored.append((hits / (1 + len(words) ** 0.5), d.name, para.strip()))
    scored.sort(reverse=True)
    if not scored:
        return "no matching passages"
    return "\n".join(f"[{name}] {para[:400]}" for _, name, para in scored[:3])


try:                                     # quantum.* tools (v0.3.2); NumPy is only needed when one is used
    import algoquantum as _algoquantum
    _algoquantum.register(register_tool)
except ImportError:  # noqa
    _algoquantum = None


def run_tool(name, query):
    """Run a registered tool. `query` is the agent's request text, or a dict of arguments (live tool use)."""
    t = TOOLS.get(name)
    if t is None:
        return None
    try:
        if isinstance(query, dict) and t.schema is None:
            query = query.get("query", json.dumps(query))
        return str(t.fn(query))
    except Exception as e:  # noqa
        return f"tool error: {type(e).__name__}: {e}"


# ═══════════════════════════════ backends ════════════════════════════════════
def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest(), 16)


class MockBackend:
    """Deterministic offline backend. Granted, registered tools really run."""
    name = "mock"

    def complete(self, spec: AgentSpec, model: str, prompt: str, goal: str, sample: int = 0):
        tool_calls, notes = [], []
        for t in spec.uses:
            out = run_tool(t, goal)
            if out is not None:
                tool_calls.append({"tool": t, "chars": len(out), "text": out[:4000]})
                notes.append(f"{t}: {out.splitlines()[0][:60] if out else ''}")
        seed = _h(spec.name, goal)
        conf = round(0.62 + (seed % 3300) / 10000, 2)           # 0.62 – 0.95
        short = (goal[:70] + "…") if len(goal) > 70 else goal
        returns = base_type(spec.returns)
        if returns == "score":
            val = round(0.55 + (seed // 7 % 4000) / 10000, 2)      # 0.55 – 0.95
            if sample:                                              # repeated samples disagree a little
                jitter = ((_h(spec.name, goal, sample) % 1600) - 800) / 10000      # ±0.08
                val = round(min(1.0, max(0.0, val + jitter)), 2)
                conf = round(min(0.97, max(0.5, conf + jitter / 2)), 2)
        elif returns == "list":
            n = 3 + seed % 2
            val = [f"item {i + 1} for: {short}" for i in range(n)]
            if spec.name.split(".")[-1].lower().startswith("plan"):
                pool = ["Novelty & contribution", "Methodology & rigour", "Experimental validity",
                        "Related-work coverage", "Clarity & presentation"]
                val = pool[: n]
        elif returns == "bool":
            val = bool(seed % 2) if not sample or _h(spec.name, goal, sample) % 5 else not bool(seed % 2)
        elif returns == "json":
            val = {"agent": spec.name, "summary": short}
        else:
            val = f"«{spec.name} #{seed % 10000:04d}» {short}"
            if notes:
                val += "  [" + " | ".join(notes) + "]"
        tokens = len(prompt) // 4 + 60
        return val, conf, tokens, tool_calls


class ClaudeBackend:
    name = "live"
    FORMATS = {
        "score": 'Reply as JSON: {"value": <number 0-1>, "confidence": <0-1>}',
        "list": 'Reply as JSON: {"value": [<strings>], "confidence": <0-1>}',
        "bool": 'Reply as JSON: {"value": true|false, "confidence": <0-1>}',
        "json": 'Reply as JSON: {"value": <object>, "confidence": <0-1>}',
        "text": 'Reply as JSON: {"value": "<text>", "confidence": <0-1>}',
    }

    def __init__(self, client=None):
        if client is None:
            import anthropic  # lazy import: only needed for live mode
            client = anthropic.Anthropic()
        self.client = client

    def complete(self, spec: AgentSpec, model: str, prompt: str, goal: str, sample: int = 0):
        max_tok = min(int(spec.policy.get("budget_tokens", 2000)), 8000)
        tools = [{"name": t.replace(".", "_"), "description": TOOLS[t].description or t,
                  "input_schema": TOOLS[t].schema or {"type": "object", "properties": {"query": {"type": "string"}},
                                                      "required": ["query"]}}
                 for t in spec.uses if t in TOOLS]
        by_api_name = {t.replace(".", "_"): t for t in spec.uses}
        messages = [{"role": "user", "content": prompt}]
        system = f"You are {spec.role or spec.name}. {self.FORMATS[base_type(spec.returns)]}. Output JSON only."
        t_in, t_out, tool_calls = 0, 0, []
        for _round in range(6):                       # at most 5 rounds of tool use
            kw = dict(model=model, max_tokens=max_tok, system=system, messages=messages)
            if tools:
                kw["tools"] = tools
            msg = self.client.messages.create(**kw)
            t_in += msg.usage.input_tokens
            t_out += msg.usage.output_tokens
            if getattr(msg, "stop_reason", None) != "tool_use":
                break
            results = []
            for b in msg.content:
                if getattr(b, "type", "") == "tool_use":
                    name = by_api_name.get(b.name, b.name)
                    granted = name in spec.uses
                    arg = (b.input or {}) if (TOOLS.get(name) and TOOLS[name].schema) else (b.input or {}).get("query", "")
                    out = run_tool(name, arg) if granted else \
                        "refused: this agent is not granted that tool"
                    tool_calls.append({"tool": name, "chars": len(out or ""), "text": (out or "")[:4000]} if granted else
                                      {"tool": name, "refused": True})
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": out or ""})
            messages += [{"role": "assistant", "content": msg.content}, {"role": "user", "content": results}]
        raw = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            data = json.loads(m.group(0)) if m else {"value": raw, "confidence": 0.5}
        except json.JSONDecodeError:
            data = {"value": raw, "confidence": 0.5}
        return data.get("value"), float(data.get("confidence", 0.5)), (t_in, t_out), tool_calls


class ReplayBackend:
    """Answers every agent call from a recorded trace (algo replay). No model calls, no tools, no cost.

    A call is matched by agent name + a hash of its prompt. If the program changed so that an agent now
    receives different inputs, the call is missing from the trace: strict replay raises ReplayMiss;
    lenient replay answers it with the offline mock backend and records it in `self.misses`."""
    name = "replay"

    def __init__(self, trace, strict=True):
        if not isinstance(trace, dict):
            trace = json.loads(Path(trace).read_text(encoding="utf-8"))
        self.trace = trace
        self.strict = strict
        self.index = {}
        for c in trace.get("calls", []):
            self.index.setdefault((c["agent"], c["inputs_sha"]), c)
        self.misses, self.hits = [], 0
        self._mock = MockBackend()
        self._lock = threading.Lock()

    def complete(self, spec, model, prompt, goal, sample=0):
        sha = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        rec = self.index.get((spec.name, sha))
        if rec is None:
            with self._lock:
                self.misses.append({"agent": spec.name, "inputs_sha": sha, "goal": goal[:200]})
            if self.strict:
                raise ReplayMiss(f"{spec.name}: its inputs changed since the trace was recorded "
                                 f"(no recorded call with this prompt)")
            return self._mock.complete(spec, model, prompt, goal, sample)
        samples = rec.get("samples") or [rec]
        s = samples[min(sample, len(samples) - 1)]
        if not sample:
            with self._lock:
                self.hits += 1
        return s["value"], s["confidence"], 0, list(s.get("tool_calls") or [])


# ═════════════════════════════════ cache ═════════════════════════════════════
class Cache:
    """Response cache in SQLite. Connections are opened per call and always closed (safe on Windows).

    Python builds without sqlite3 (Pyodide in the web playground, some minimal containers) fall back to an
    in-memory cache for the life of the process, so caching never stops a program from running."""
    _lock = threading.Lock()

    def __init__(self, path):
        self.path = Path(path)
        try:
            import sqlite3  # noqa: F401
            self.memory = None
        except ImportError:
            self.memory = {}
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._db() as db:
            db.execute("create table if not exists calls (key text primary key, value text, conf real, ts text)")

    @contextlib.contextmanager
    def _db(self):
        import sqlite3
        db = sqlite3.connect(self.path)
        try:
            yield db
            db.commit()
        finally:
            db.close()

    @staticmethod
    def key(*parts):
        return hashlib.sha256("\x1f".join(map(str, parts)).encode()).hexdigest()

    def get(self, key):
        if self.memory is not None:
            return self.memory.get(key)
        with self._lock, self._db() as db:
            row = db.execute("select value, conf from calls where key=?", (key,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def put(self, key, value, conf):
        if self.memory is not None:
            self.memory[key] = (json.loads(json.dumps(value, default=str)), conf)
            return
        with self._lock, self._db() as db:
            db.execute("insert or replace into calls values (?,?,?,?)",
                       (key, json.dumps(value, default=str), conf, time.strftime("%Y-%m-%dT%H:%M:%S")))


# ══════════════════════════ tamper-evident audit log ═════════════════════════
_AUDIT_LOCK = threading.Lock()


def _last_hash(path: Path):
    if not path.exists() or path.stat().st_size == 0:
        return "0" * 64
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 65536))
        tail = f.read().decode("utf-8", errors="replace").strip().splitlines()
    try:
        return json.loads(tail[-1]).get("hash", "0" * 64)
    except Exception:  # noqa
        return "0" * 64


def _record_hash(prev, rec):
    body = json.dumps(rec, sort_keys=True, default=str)
    return hashlib.sha256((prev + body).encode()).hexdigest()


def append_audit(path: Path, rec: dict):
    """Append a record whose hash covers the previous record's hash (a hash chain)."""
    with _AUDIT_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        prev = _last_hash(path)
        rec = dict(rec, prev=prev)
        rec["hash"] = _record_hash(prev, {k: v for k, v in rec.items() if k != "hash"})
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        return rec


def verify_audit(path):
    """Check every record's hash and link. Returns dict(ok, records, first_bad_line, reason)."""
    prev, n = "0" * 64, 0
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            return {"ok": False, "records": n - 1, "first_bad_line": n, "reason": "not valid JSON"}
        if "hash" not in rec:
            return {"ok": False, "records": n - 1, "first_bad_line": n, "reason": "record has no hash (v0.1 log?)"}
        if rec.get("prev") != prev:
            return {"ok": False, "records": n - 1, "first_bad_line": n, "reason": "chain broken: a record was removed or reordered"}
        if _record_hash(prev, {k: v for k, v in rec.items() if k != "hash"}) != rec["hash"]:
            return {"ok": False, "records": n - 1, "first_bad_line": n, "reason": "record was modified"}
        prev = rec["hash"]
    return {"ok": True, "records": n, "first_bad_line": None, "reason": ""}


# ═══════════════════════════════ review queue ════════════════════════════════
def audit_dir():
    return Path(os.environ.get("ALGO_AUDIT_DIR") or load_config().get("audit_dir") or "runs")


def review_queue_path():
    q = load_config().get("review_queue")
    return Path(q) if q else audit_dir() / "review_queue.jsonl"


def queue_for_review(item: dict):
    append_audit(review_queue_path(), dict(type="item", status="pending", **item))


def list_reviews(status="pending", path=None):
    """Items in the review queue with their latest decision applied."""
    p = Path(path) if path else review_queue_path()
    if not p.exists():
        return []
    items = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("type") == "item":
            items[r["id"]] = r
        elif r.get("type") == "decision" and r.get("item") in items:
            items[r["item"]].update(status=r["decision"], reviewer=r.get("reviewer"),
                                    note=r.get("note"), decided=r.get("ts"))
    out = list(items.values())
    return [i for i in out if status in (None, "all") or i["status"] == status]


def decide_review(item_id, decision, reviewer="", note="", path=None):
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be 'approved' or 'rejected'")
    p = Path(path) if path else review_queue_path()
    known = {i["id"] for i in list_reviews("all", p)}
    match = [i for i in known if i.startswith(item_id)]
    if len(match) != 1:
        raise KeyError(f"no single review item matches '{item_id}'")
    append_audit(p, dict(type="decision", item=match[0], decision=decision, reviewer=reviewer,
                         note=note, ts=time.strftime("%Y-%m-%dT%H:%M:%S")))
    return match[0]


# ═══════════════════════════════ runtime ═════════════════════════════════════
class Runtime:
    def __init__(self, program: str, quiet: bool | None = None, backend=None, live: bool | None = None,
                 audit_dir_override: str | None = None, trace: bool | str | None = None, source: str | None = None):
        self.program = program
        self.source = source or os.environ.get("ALGO_SOURCE")
        self.cfg = load_config()
        self.models = {}
        self.tools = set()
        self.quiet = (os.environ.get("ALGO_QUIET") == "1") if quiet is None else quiet
        self.live = (os.environ.get("ALGO_LIVE") == "1") if live is None else live
        if backend is not None:
            self.backend = backend
        elif self.live:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise SystemExit("✗ --live needs ANTHROPIC_API_KEY to be set "
                                 "(Colab: add it under Secrets; terminal: see RUN_GUIDE.md, step 5)")
            try:
                self.backend = ClaudeBackend()
            except ImportError:
                raise SystemExit("✗ --live needs the anthropic package:  pip install anthropic")
        else:
            self.backend = MockBackend()
        self.emitted = []
        self.calls = []
        self.lock = threading.Lock()
        self.stats = {"calls": 0, "tokens": 0, "escalations": 0, "retries": 0, "blocked": 0, "cache_hits": 0,
                      "tool_calls": 0, "cost_usd": 0.0, "energy_wh": 0.0, "co2_g": 0.0}
        self.run_id = uuid.uuid4().hex[:8]
        adir = Path(audit_dir_override) if audit_dir_override else audit_dir()
        adir.mkdir(parents=True, exist_ok=True)
        self.audit_path = adir / f"{program}.audit.jsonl"
        c = self.cfg.get("cache") or {}
        self.cache = Cache(c.get("path") or adir / "cache.sqlite")
        self.cache_all = bool(c.get("enabled")) and getattr(self.backend, "name", "") != "replay"
        # traces: every call's inputs and outputs, so `algo replay` can re-run this exact run offline
        trace = os.environ.get("ALGO_TRACE") if trace is None else trace
        self.trace_calls = [] if trace else None
        self.trace_path = (Path(trace) if isinstance(trace, str) and trace not in ("1", "true")
                           else adir / "traces" / f"{program}-{self.run_id}.trace.json") if trace else None
        self.flow_name, self.flow_inputs = None, {}
        if not self.quiet:
            for s in (sys.stdout, sys.stderr):
                try:
                    s.reconfigure(encoding="utf-8", errors="replace")
                except Exception:  # noqa
                    pass

    # declarations ---------------------------------------------------
    def model(self, name, model_id):
        self.models[name] = (self.cfg.get("models") or {}).get(name, model_id)

    def tool(self, name):
        self.tools.add(name)

    def mcp_tool(self, name, server):
        """`tool name from mcp "server"`: register a tool that calls the MCP server (started on first use)."""
        self.tools.add(name)
        if name not in TOOLS:
            import algomcp
            algomcp.bind_tool(name, server, (self.cfg.get("mcp_servers") or {}).get(server))

    def agent(self, spec: AgentSpec):
        rt = self

        def call(**kwargs):
            return rt._invoke(spec, kwargs)

        call.__name__ = spec.name.replace(".", "__")
        call.spec = spec
        return call

    # helpers --------------------------------------------------------
    @staticmethod
    def value(x):
        return x.value if isinstance(x, Result) else x

    @staticmethod
    def contains(x, needle):
        """`if limits contains "BREACH"`: a deterministic, case-insensitive text guard — no model involved.
        For tool-using agents the tool's full answer is searched, not only the agent's summary."""
        hay = str(Runtime.value(x))
        extra = getattr(x, "tool_text", "") if isinstance(x, Result) else ""
        return needle.lower() in (hay + "\n" + extra).lower()

    @staticmethod
    def conf(x):
        """`x.confidence` in a condition: an agent result's confidence (1.0 for plain values)."""
        return x.confidence if isinstance(x, Result) else 1.0

    def _log(self, msg):
        if not self.quiet:
            with self.lock:
                print(msg, flush=True)

    def _audit(self, rec, output=None):
        rec.update(run=self.run_id, program=self.program, ts=time.strftime("%Y-%m-%dT%H:%M:%S"))
        rec = append_audit(self.audit_path, rec)
        with self.lock:
            self.calls.append(dict(rec, output=output))   # in-memory copy for notebooks and the SDK

    def effective_policy(self, spec):
        """The agent's policy combined with the organisation's; the stricter rule wins."""
        pol = dict(spec.policy)
        org = self.cfg.get("policy") or {}
        if org.get("forbid"):
            pol["forbid"] = list(dict.fromkeys(list(pol.get("forbid", [])) + list(org["forbid"])))
        if org.get("max_budget_tokens"):
            pol["budget_tokens"] = min(pol.get("budget_tokens", org["max_budget_tokens"]), org["max_budget_tokens"])
        if org.get("min_human_below") is not None:
            pol["human_below"] = max(pol.get("human_below", 0), org["min_human_below"])
        for key in ("max_budget_cost_usd", "max_budget_energy_wh"):       # org caps per agent call (v0.3)
            if org.get(key) is not None:
                k = key.replace("max_", "")
                pol[k] = min(pol.get(k, org[key]), org[key])
        return pol

    # the heart: one agent call -------------------------------------
    def _invoke(self, spec: AgentSpec, kwargs):
        pol = self.effective_policy(spec)
        org = self.cfg.get("policy") or {}
        args = {}
        for name, _typ, default in spec.params:
            args[name] = self.value(kwargs[name]) if name in kwargs else default
        call_id = uuid.uuid4().hex[:6]
        model_id = self.models.get(spec.model, "claude-sonnet-5-5") if spec.model else \
            (self.cfg.get("models") or {}).get("default", "claude-sonnet-5-5")

        def fmt(v):
            if isinstance(v, list):
                return "; ".join(map(str, (self.value(x) for x in v)))
            return str(v)
        goal = re.sub(r"\{(\w+)\}", lambda m: fmt(args.get(m.group(1), m.group(0))), spec.goal)
        prompt = f"ROLE: {spec.role}\nGOAL: {goal}\nTOOLS: {', '.join(spec.uses) or 'none'}"

        def block(reason, msg):
            with self.lock:
                self.stats["blocked"] += 1
            self._audit(dict(call=call_id, agent=spec.name, status="blocked", reason=reason, policy=pol))
            raise PolicyViolation(f"{spec.name}: {msg}")

        # organisation: only approved tools
        allowed = org.get("allowed_tools")
        if allowed is not None:
            for t in spec.uses:
                if t not in allowed:
                    block(f"tool '{t}' not allowed by organisation policy", f"tool '{t}' is not allowed by organisation policy")
        # policy: forbidden attributes must not appear in the inputs
        for attr in pol.get("forbid", []):
            if re.search(rf"\b{re.escape(attr)}\b", prompt, re.I):
                block(f"forbidden attribute '{attr}'", f"input mentions forbidden attribute '{attr}'")
        # policy: token budget (pre-flight estimate)
        budget = pol.get("budget_tokens")
        if budget and len(prompt) // 4 > budget:
            block(f"prompt ~{len(prompt)//4} tokens exceeds budget {budget}",
                  f"prompt (~{len(prompt)//4} tok) exceeds budget {budget}")
        # organisation: run-level token cap
        cap = self.cfg.get("max_run_tokens")
        if cap and self.stats["tokens"] + len(prompt) // 4 > cap:
            block(f"run token cap {cap} reached", f"this run reached the organisation's token cap ({cap})")
        # v0.3: money and energy, priced before the call (pre-flight) and after it (actual)
        k = max(1, int(pol.get("samples", 3))) if spec.returns.startswith("uncertain<") else 1
        est_in, est_out = len(prompt) // 4 * k, int(self.cfg.get("estimate_output_tokens") or 500) * k
        est_cost, est_wh = price_usd(model_id, est_in, est_out, self.cfg), energy_wh(model_id, est_in + est_out, self.cfg)
        rate = float(self.cfg.get("usd_to_inr") or 84.0)
        limits = [(pol.get("budget_cost_usd"), est_cost, "USD", 1.0), (pol.get("budget_cost_inr"), est_cost * rate, "INR", 1.0),
                  (pol.get("budget_energy_wh"), est_wh, "Wh", 1.0)]
        if getattr(self.backend, "name", "") != "replay":
            for lim, est, unit, _ in limits:
                if lim is not None and est > lim:
                    block(f"estimated {est:.4f} {unit} exceeds budget {lim} {unit}",
                          f"estimated cost {est:.4f} {unit} exceeds the agent's budget ({lim} {unit})")
            for key, cur, est, unit in (("max_run_cost_usd", self.stats["cost_usd"], est_cost, "USD"),
                                        ("max_run_energy_wh", self.stats["energy_wh"], est_wh, "Wh")):
                lim = self.cfg.get(key)
                if lim is not None and cur + est > lim:
                    block(f"run cap {lim} {unit} reached", f"this run would exceed the organisation's cap ({lim} {unit})")

        use_cache = self.cache_all or pol.get("cache")
        ckey = Cache.key("v3", self.backend.name, model_id, spec.returns, spec.role, prompt, k) if use_cache else None
        hit = self.cache.get(ckey) if use_cache else None
        tool_calls, cached, t_in, t_out, samples = [], False, 0, 0, None
        if hit is not None:
            val, conf = hit
            tokens, cached = 0, True
            if isinstance(val, dict) and "__entry__" in val:          # v0.3 entry: keeps samples and tool results
                samples, tool_calls, val = val.get("samples"), list(val.get("tool_calls") or []), val["value"]
            elif isinstance(val, dict) and "__uncertain__" in val:
                samples, val = val["samples"], val["value"]
            with self.lock:
                self.stats["cache_hits"] += 1
        else:
            draws = [self._sample(spec, model_id, prompt, goal, pol, call_id, i, k) for i in range(k)]
            for d in draws:
                t_in += d["t_in"]
                t_out += d["t_out"]
                tool_calls += d["tool_calls"]
            if k == 1:
                val, conf = draws[0]["value"], draws[0]["confidence"]
            else:
                val, conf, samples = self._aggregate(spec, draws)
            tokens = t_in + t_out
            if use_cache:
                self.cache.put(ckey, {"__entry__": 3, "value": val, "samples": samples, "tool_calls": tool_calls}, conf)
        res = Result(val, conf, spec.name, call_id)
        res.tool_text = "\n".join(t.get("text", "") for t in tool_calls)
        trace_tools = tool_calls
        tool_calls = [{k: v for k, v in t.items() if k != "text"} for t in tool_calls]   # audit: no tool payloads
        if samples is not None:
            res.samples = [d["value"] for d in samples]
            vals = [x for x in res.samples if isinstance(x, (int, float)) and not isinstance(x, bool)]
            res.spread = round(_stdev(vals), 3) if len(vals) == len(res.samples) else \
                round(1 - max(res.samples.count(x) for x in res.samples) / len(res.samples), 3)
        cost = price_usd(model_id, t_in, t_out, self.cfg) if not cached else 0.0
        wh = energy_wh(model_id, tokens, self.cfg) if not cached else 0.0
        over = [u for lim, act, u in ((pol.get("budget_cost_usd"), cost, "USD"),
                                      (pol.get("budget_cost_inr"), cost * float(self.cfg.get("usd_to_inr") or 84), "INR"),
                                      (pol.get("budget_energy_wh"), wh, "Wh")) if lim is not None and act > lim]

        # policy: human-in-the-loop gate
        gate = pol.get("human_below")
        if gate is not None and conf < gate:
            res.status = self._human_review(spec, res, gate)
            if res.status == "escalated":
                queue_for_review(dict(id=uuid.uuid4().hex[:10], program=self.program, run=self.run_id, call=call_id,
                                      agent=spec.name, confidence=conf, threshold=gate,
                                      output=str(val)[:2000], ts=time.strftime("%Y-%m-%dT%H:%M:%S")))

        with self.lock:
            self.stats["calls"] += 1
            self.stats["tokens"] += tokens
            self.stats["tool_calls"] += len(tool_calls)
            self.stats["cost_usd"] = round(self.stats["cost_usd"] + cost, 6)
            self.stats["energy_wh"] = round(self.stats["energy_wh"] + wh, 4)
            self.stats["co2_g"] = round(co2_grams(self.stats["energy_wh"], self.cfg), 4)
        shown = val if not isinstance(val, list) else f"[{len(val)} items]"
        flag = {"ok": "", "escalated": "  ⚠ ESCALATED to human (conf < %.2f)" % (gate or 0),
                "approved": "  ✔ human-approved"}[res.status]
        spread = f"  ±{res.spread:.2f} over {k} samples" if res.spread is not None else ""
        warn = f"  ⚠ OVER {'/'.join(over)} BUDGET" if over else ""
        self._log(f"  → {spec.name:<18} conf={conf:.2f}  {str(shown)[:72]}{spread}{flag}{warn}{'  (cached)' if cached else ''}")
        sha = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        rec = dict(call=call_id, agent=spec.name, model=model_id, backend=self.backend.name, inputs_sha=sha,
                   returns=spec.returns, confidence=conf, tokens=tokens, status=res.status, cached=cached,
                   tools=spec.uses, tool_calls=tool_calls, policy=pol, cost_usd=round(cost, 6), energy_wh=round(wh, 4))
        if samples is not None:
            rec.update(samples=k, spread=res.spread)
        if over:
            rec["over_budget"] = over
        self._audit(rec, output=val)
        if self.trace_calls is not None:
            with self.lock:
                self.trace_calls.append(dict(agent=spec.name, inputs_sha=sha, goal=goal, returns=spec.returns,
                                             value=_jsonable(val), confidence=conf, tokens=tokens,
                                             tool_calls=trace_tools,
                                             samples=[dict(value=_jsonable(d["value"]), confidence=d["confidence"],
                                                           tool_calls=d["tool_calls"]) for d in samples]
                                             if samples else None))
        return res

    def _sample(self, spec, model_id, prompt, goal, pol, call_id, i, k):
        """One model call (one sample), with retries and timeout."""
        tries = 1 + int(pol.get("retry", 0))
        for attempt in range(1, tries + 1):
            try:
                t0 = time.time()
                qtok = _algoquantum.POLICY.set(pol) if _algoquantum else None    # shots / max qubits for quantum tools
                try:
                    with _semaphore():
                        out = self.backend.complete(spec, model_id, prompt, goal, sample=i) if k > 1 or i else \
                            self.backend.complete(spec, model_id, prompt, goal)
                finally:
                    if qtok is not None:
                        _algoquantum.POLICY.reset(qtok)
                val, conf, tokens, tool_calls = out
                dt = time.time() - t0
                if pol.get("timeout_s") and dt > pol["timeout_s"]:
                    raise TimeoutError(f"{spec.name} exceeded {pol['timeout_s']}s")
                if isinstance(tokens, (tuple, list)):
                    t_in, t_out = int(tokens[0]), int(tokens[1])
                else:
                    t_in = min(int(tokens), len(prompt) // 4)
                    t_out = int(tokens) - t_in
                return dict(value=val, confidence=float(conf), t_in=t_in, t_out=t_out, tool_calls=list(tool_calls or []))
            except (PolicyViolation, ReplayMiss):
                raise
            except Exception as e:  # noqa
                with self.lock:
                    self.stats["retries"] += 1
                if attempt == tries:
                    self._audit(dict(call=call_id, agent=spec.name, status="failed", error=str(e)[:500]))
                    raise

    @staticmethod
    def _aggregate(spec, draws):
        """uncertain<T>: combine k samples. Scores → mean; anything else → majority vote.
        Confidence = half the models' own confidence, half how much the samples agree."""
        vals = [d["value"] for d in draws]
        mean_conf = sum(d["confidence"] for d in draws) / len(draws)
        if base_type(spec.returns) == "score" and all(isinstance(v, (int, float)) for v in vals):
            val = round(sum(vals) / len(vals), 3)
            agreement = max(0.0, 1 - _stdev(vals) / 0.25)
        else:
            keys = [json.dumps(v, sort_keys=True, default=str) for v in vals]
            top = max(set(keys), key=keys.count)
            val = vals[keys.index(top)]
            agreement = keys.count(top) / len(keys)
        conf = round(0.5 * mean_conf + 0.5 * agreement, 2)
        return val, conf, draws

    def _human_review(self, spec, res, gate):
        with self.lock:
            self.stats["escalations"] += 1
        if os.environ.get("ALGO_INTERACTIVE") == "1" and not self.quiet:
            try:
                with self.lock:
                    ans = input(f"\n[HUMAN REVIEW] {spec.name} (conf {res.confidence:.2f}) → {res.value}\napprove? [y/N] ")
                return "approved" if ans.strip().lower() == "y" else "escalated"
            except Exception:  # noqa — no input available (headless run)
                return "escalated"
        return "escalated"   # queued for a human (review queue + audit log)

    # concurrency ----------------------------------------------------
    def par(self, *thunks):
        if not CAN_THREAD:
            return [t() for t in thunks]
        with ThreadPoolExecutor(max_workers=len(thunks)) as ex:
            return [f.result() for f in [ex.submit(t) for t in thunks]]

    def par_map(self, fn, items):
        items = self.value(items)
        if not isinstance(items, list):
            items = [items]
        if not CAN_THREAD:
            return [fn(it) for it in items]
        with ThreadPoolExecutor(max_workers=max(1, min(len(items), 64))) as ex:
            return [f.result() for f in [ex.submit(fn, it) for it in items]]

    # flow lifecycle -------------------------------------------------
    def begin_flow(self, name, args):
        self.flow_name, self.flow_inputs = name, dict(args)
        self._log(f"▶ flow {name}  run={self.run_id}  backend={self.backend.name}")
        for k, v in args.items():
            self._log(f"    {k} = {v!r}")

    def emit(self, *vals):
        self.emitted.extend(vals)

    def write_trace(self, values=None, status="ok", problem=None):
        """Save this run's trace (inputs, every agent call, outputs) for `algo replay`."""
        if self.trace_calls is None or self.trace_path is None:
            return None
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        vals = [self.value(v) for v in (self.emitted if values is None else values)]
        src_sha = None
        if self.source and Path(self.source).exists():
            src_sha = hashlib.sha256(Path(self.source).read_bytes()).hexdigest()[:16]
        doc = dict(algolang=VERSION, program=self.program, source=self.source, source_sha=src_sha,
                   run=self.run_id, flow=self.flow_name,
                   inputs=self.flow_inputs, backend=self.backend.name, status=status, problem=problem,
                   recorded=time.strftime("%Y-%m-%dT%H:%M:%S"), stats=dict(self.stats),
                   values=_jsonable(vals), calls=self.trace_calls)
        self.trace_path.write_text(json.dumps(doc, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        return self.trace_path

    def end_flow(self):
        s = self.stats
        self.write_trace()
        if os.environ.get("ALGO_NOTEBOOK") == "1" or self.quiet:
            return [self.value(v) for v in self.emitted]
        self._log("■ emitted:")
        for v in self.emitted:
            v = self.value(v)
            if isinstance(v, list):
                for x in v:
                    self._log(f"    • {self.value(x)}")
            else:
                self._log(f"    • {v}")
        extra = f" · {s['cache_hits']} cached" if s["cache_hits"] else ""
        extra += f" · {s['tool_calls']} tool calls" if s["tool_calls"] else ""
        if s["cost_usd"] or s["energy_wh"]:
            est = "est. live " if self.backend.name == "mock" else ""
            extra += f" · {est}${s['cost_usd']:.4f} · {s['energy_wh']:.3f} Wh · {s['co2_g']:.2f} g CO₂"
        if self.trace_path is not None:
            extra += f" · trace → {self.trace_path}"
        self._log(f"■ {s['calls']} agent calls · ~{s['tokens']} tokens · {s['retries']} retries · "
                  f"{s['escalations']} escalated · {s['blocked']} blocked{extra} · audit → {self.audit_path}")
        return [self.value(v) for v in self.emitted]

    def cli(self, flow, params):
        ap = argparse.ArgumentParser(prog=self.program)
        for p in params:
            ap.add_argument(f"--{p}")
        a = ap.parse_args()
        vals = {}
        for p in params:
            v = getattr(a, p)
            if v is None:
                if not sys.stdin.isatty():
                    self._log(f'✗ missing input: add --arg "{p}=..."')
                    sys.exit(1)
                v = input(f"{p}: ")
            vals[p] = v
        try:
            flow(**vals)
        except PolicyViolation as e:
            self.write_trace(status="blocked", problem=str(e))
            self._log(f"✗ POLICY VIOLATION: {e}")
            sys.exit(2)
        except Exception as e:  # noqa — model/API failures after retries
            self.write_trace(status="failed", problem=f"{type(e).__name__}: {e}")
            self._log(f"✗ agent call failed: {type(e).__name__}: {str(e)[:300]}")
            self._log(f"  details are in the audit log: {self.audit_path}")
            sys.exit(3)
