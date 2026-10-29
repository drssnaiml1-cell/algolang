"""
AlgoLang SDK  (v0.2 "Enterprise")
AlgoProfessor AI R&D Solutions

The one Python API behind all three ways of working — the `algo` command line, AlgoLang Studio
(graphical) and the Prompt UI. Use it to embed governed multi-agent programs in your own systems.

    import algolang as al

    prog = al.load("claims.algo")                     # or al.compile(source) or al.pack("insurance.claims_triage")
    res  = prog.run(claim="Rear-end collision, Pune")  # RunResult: values, calls, stats, ok, problem
    rows = prog.run_batch([{"claim": c} for c in claims], workers=16)

    al.domains.search("triage insurance claims")       # 120 domain packs in 20 sectors
    al.compose("check this NDA against our playbook")  # prompt → best domain pack → ready program

    @al.tool("crm.lookup", "Look up a customer by name or ID")
    def crm_lookup(query: str) -> str: ...

    al.configure(policy={"forbid": ["salary"], "min_human_below": 0.8}, max_concurrency=32)
    al.audit.verify("runs/claims.audit.jsonl");  al.audit.report("runs")
    al.review.pending();  al.review.approve(item_id, reviewer="Dr. S")
"""
from __future__ import annotations

import builtins
import csv
import json
import math
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

_PKG = Path(__file__).resolve().parent
# Installed with pip, the engine and its data live in algolang/_home; in a source checkout they sit
# next to this package.
HOME = _PKG / "_home" if (_PKG / "_home" / "algoc.py").exists() else _PKG.parent
if str(HOME) not in sys.path:
    sys.path.insert(0, str(HOME))
os.environ.setdefault("ALGO_HOME", str(HOME))

import algoruntime as _rt  # noqa: E402
from algoc import CompileError, Diag, compile_source, flow_graph  # noqa: E402

__version__ = _rt.VERSION
__all__ = ["compile", "load", "pack", "Program", "RunResult", "CompileError", "tool", "configure",
           "domains", "compose", "ask", "audit", "review", "batch_csv"]

PolicyViolation = _rt.PolicyViolation
configure = _rt.configure
tool = _rt.register_tool


# ══════════════════════════════ programs ═════════════════════════════════════
@dataclass
class RunResult:
    values: list = field(default_factory=list)
    calls: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    run_id: str = ""
    ok: bool = True
    problem: str | None = None          # policy violation or failure message
    status: str = "ok"                  # ok | blocked | failed
    inputs: dict = field(default_factory=dict)
    audit_path: str = ""

    @property
    def escalated(self):
        return [c for c in self.calls if c.get("status") == "escalated"]

    def to_dict(self):
        def j(v):
            v = _rt.Runtime.value(v)
            return [j(x) for x in v] if isinstance(v, list) else (v if isinstance(v, (str, int, float, bool, type(None))) else str(v))
        return dict(run_id=self.run_id, ok=self.ok, status=self.status, problem=self.problem, inputs=self.inputs,
                    values=[j(v) for v in self.values], stats=self.stats, audit_path=self.audit_path,
                    calls=[{k: (j(v) if k == "output" else v) for k, v in c.items()} for c in self.calls])


class Program:
    """A compiled, checked AlgoLang program."""

    def __init__(self, source: str, name: str = "program", base_dir=None):
        self.source, self.name = source, re.sub(r"\W+", "_", Path(name).stem) or "program"
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.python, self._prog = compile_source(source, f"{self.name}.algo", self.base_dir)
        self._code = builtins.compile(self.python, f"<algolang:{self.name}>", "exec")

    # facts about the program
    @property
    def inputs(self):
        return [p.name for p in self._prog.flows["main"].params]

    @property
    def agents(self):
        return sorted(self._prog.agents)

    @property
    def tools(self):
        return sorted(self._prog.tools)

    @property
    def imports(self):
        return list(self._prog.imports)

    def policies(self):
        return {n: a.policy for n, a in self._prog.agents.items()}

    def graph(self):
        nodes, edges = flow_graph(self._prog)
        return {"nodes": [dict(id=a, label=b, kind=c, sub=d) for a, b, c, d in nodes],
                "edges": [dict(src=a, dst=b, dashed=c) for a, b, c in edges]}

    # running
    def run(self, live: bool = False, quiet: bool = True, audit_dir: str | None = None, backend=None,
            **inputs) -> RunResult:
        missing = [p for p in self.inputs if p not in inputs]
        if missing:
            raise TypeError(f"{self.name}: missing input(s): {', '.join(missing)}")
        ns = {"__name__": "algolang_sdk",
              "__algo_runtime__": dict(quiet=quiet, live=live, backend=backend, audit_dir_override=audit_dir)}
        exec(self._code, ns)
        rt = ns["rt"]
        res = RunResult(run_id=rt.run_id, inputs={k: inputs[k] for k in self.inputs},
                        audit_path=str(rt.audit_path))
        try:
            res.values = ns["flow_main"](**{k: str(inputs[k]) for k in self.inputs}) or []
        except _rt.PolicyViolation as e:
            res.ok, res.status, res.problem = False, "blocked", str(e)
        except Exception as e:  # noqa
            res.ok, res.status, res.problem = False, "failed", f"{type(e).__name__}: {e}"
        res.calls, res.stats = list(rt.calls), dict(rt.stats)
        return res

    def run_batch(self, rows, workers: int = 8, live: bool = False, audit_dir: str | None = None,
                  progress=None, quiet: bool = True) -> list[RunResult]:
        """Run the flow once per row (dict of inputs), in parallel. Model calls stay within max_concurrency."""
        rows = list(rows)
        out = [None] * len(rows)
        done = [0]
        lock = threading.Lock()

        def one(i):
            out[i] = self.run(live=live, quiet=quiet, audit_dir=audit_dir, **rows[i])
            with lock:
                done[0] += 1
                if progress:
                    progress(done[0], len(rows))

        if not _rt.CAN_THREAD:
            for i in range(len(rows)):
                one(i)
        else:
            with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
                list(ex.map(one, range(len(rows))))
        return out

    def __repr__(self):
        return f"<AlgoLang Program {self.name}: {len(self.agents)} agents, inputs={self.inputs}>"


def compile(source: str, name: str = "program", base_dir=None) -> Program:  # noqa: A001
    """Compile AlgoLang source. Raises CompileError with every problem found."""
    return Program(source, name, base_dir)


def load(path) -> Program:
    p = Path(path)
    return Program(p.read_text(encoding="utf-8"), p.stem, p.resolve().parent)


def pack(pack_id: str) -> Program:
    """Load a domain pack from the library, e.g. al.pack("insurance.claims_triage")."""
    meta = domains.get(pack_id)
    return load(HOME / meta["path"])


def batch_csv(program: Program, in_path, out_path, workers: int = 8, live=False, progress=None):
    """Run a program over every row of a CSV file and write results to another CSV.

    Columns whose names match the flow's inputs are used; with one input and no matching column,
    the first column is used."""
    with open(in_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols, raw = reader.fieldnames or [], list(reader)
    rows = []
    for r in raw:
        if all(i in r for i in program.inputs):
            rows.append({i: r[i] for i in program.inputs})
        elif len(program.inputs) == 1 and cols:
            rows.append({program.inputs[0]: r[cols[0]]})
        else:
            raise ValueError(f"CSV needs columns named {', '.join(program.inputs)}")
    results = program.run_batch(rows, workers=workers, live=live, progress=progress)
    width = max((len(r.values) for r in results), default=0)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["row", *program.inputs, "status", "escalated", "tokens", "run_id", "problem",
                    *[f"output_{i + 1}" for i in range(width)]])
        for n, r in enumerate(results, 1):
            vals = [_rt.Runtime.value(v) for v in r.values]
            vals = ["; ".join(map(str, (_rt.Runtime.value(x) for x in v))) if isinstance(v, list) else v for v in vals]
            w.writerow([n, *[r.inputs.get(i, "") for i in program.inputs], r.status, len(r.escalated),
                        r.stats.get("tokens", 0), r.run_id, r.problem or "", *vals])
    return results


# ═══════════════════════════════ domains ═════════════════════════════════════
_SYN = {"cv": "resume", "cvs": "resume", "hiring": "resume screening recruit", "recruitment": "resume screening",
        "invoice": "document", "bug": "incident", "outage": "outage incident", "ticket": "helpdesk query",
        "doctor": "clinical", "hospital": "clinical patient", "medicine": "drug prescription",
        "farmer": "farmer crop agriculture", "crops": "crop", "student": "student education",
        "exam": "exam question", "paper": "manuscript research", "journal": "manuscript peer review",
        "loan": "loan credit", "kyc": "kyc customer", "fraud": "fraud", "contract": "contract clause",
        "law": "legal case", "court": "litigation dispute", "phishing": "phishing email", "malware": "alert soc",
        "hack": "alert incident soc", "tender": "tender bids", "citizen": "citizen grievance",
        "complaint": "complaint grievance query", "esg": "esg environmental governance", "carbon": "emissions",
        "shipping": "shipment", "warehouse": "inventory stock", "hotel": "guest booking", "menu": "menu allergen",
        "server": "incident service", "servers": "incident service", "down": "incident",
        "crash": "incident", "website": "incident service", "water": "citizen grievance government",
        "road": "citizen grievance government", "municipal": "citizen grievance government",
        "public": "citizen public government", "electricity": "outage energy meter", "power": "outage energy grid",
        "patient": "patient clinical", "vendor": "supplier", "supplier": "supplier", "salary": "employee hr",
        "employee": "employee hr", "customer": "customer",
        # agriculture: symptoms people describe in plain words
        "leaf": "pest disease crop", "leaves": "pest disease crop", "insects": "pest", "insect": "pest",
        "aphids": "pest", "whitefly": "pest", "worms": "pest", "spots": "disease pest", "wilting": "disease crop",
        "fungus": "disease pest", "cotton": "crop", "paddy": "crop", "rice": "crop", "wheat": "crop",
        "plant": "crop", "plants": "crop", "seeds": "crop", "fertiliser": "soil crop", "fertilizer": "soil crop",
        "harvest": "crop market", "mandi": "market prices",
        # government services
        "street": "citizen grievance government", "streetlight": "citizen grievance government",
        "lights": "citizen grievance", "ward": "citizen grievance government", "garbage": "citizen grievance",
        "drainage": "citizen grievance", "pothole": "citizen grievance government", "plagiarism": "originality",
        "copied": "originality"}


# words that point strongly at one sector; matching packs get a small boost
SECTOR_HINTS = {
    "government": "citizen citizens public municipal water road ration panchayat ministry department government rti "
                  "street streetlight ward garbage drainage pothole",
    "itops": "server servers it network database website app application helpdesk deployment kubernetes",
    "energy": "power electricity grid solar wind meter substation",
    "healthcare": "patient patients hospital clinic doctor nurse clinical",
    "banking": "bank banking loan account card kyc aml",
    "insurance": "insurance claim claims policyholder premium",
    "education": "student students exam course teacher school college university",
    "research": "research thesis manuscript journal grant phd",
    "agriculture": "farmer farmers crop crops soil pest mandi cotton paddy rice wheat leaf leaves insects "
                   "aphids whitefly plant plants harvest fertiliser fertilizer irrigation",
    "hr": "employee employees hiring resume cv candidate interview",
    "legal": "contract nda law legal court litigation clause",
    "cyber": "phishing malware vulnerability soc threat breach",
    "retail": "shop store product products ecommerce order returns",
    "hospitality": "hotel guest guests restaurant travel trip booking",
}
_HINTS = {sec: set(words.split()) for sec, words in SECTOR_HINTS.items()}


def _stem(w):
    for suf in ("ations", "ation", "ings", "ing", "ies", "es", "ed", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def _tokens(text):
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        out += [_stem(x) for x in (w + " " + _SYN.get(w, "")).split() if len(x) > 1]
    return out


class _Domains:
    def __init__(self):
        self._cat = None
        self._index = None

    def _load(self):
        if self._cat is None:
            p = HOME / "packs" / "catalog.json"
            self._cat = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"packs": [], "sectors": {}}
            docs = []
            for m in self._cat["packs"]:
                src = (HOME / m["path"]).read_text(encoding="utf-8") if (HOME / m["path"]).exists() else ""
                goals = " ".join(re.findall(r'goal\s+"([^"]*)"', src))
                text = " ".join([m["title"]] * 3 + [m["description"]] * 2 + [m["sector_name"], m["id"].replace(".", " ").replace("_", " "), goals])
                docs.append(_tokens(text))
            n = len(docs)
            df = {}
            for d in docs:
                for t in set(d):
                    df[t] = df.get(t, 0) + 1
            self._idf = {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}
            self._vecs = []
            for d in docs:
                tf = {}
                for t in d:
                    tf[t] = tf.get(t, 0) + 1
                v = {t: (1 + math.log(c)) * self._idf[t] for t, c in tf.items()}
                norm = math.sqrt(sum(x * x for x in v.values())) or 1
                self._vecs.append({t: x / norm for t, x in v.items()})
        return self._cat

    def all(self, sector=None):
        packs = self._load()["packs"]
        return [p for p in packs if sector in (None, p["sector"])]

    def sectors(self):
        cat = self._load()
        counts = {}
        for p in cat["packs"]:
            counts[p["sector"]] = counts.get(p["sector"], 0) + 1
        return [{"id": k, "name": v, "packs": counts.get(k, 0)} for k, v in cat["sectors"].items()]

    def get(self, pack_id):
        for p in self._load()["packs"]:
            if p["id"] == pack_id:
                return p
        raise KeyError(f"no domain pack '{pack_id}' — see al.domains.search(...)")

    def search(self, query, k=5):
        """Best-matching domain packs for a plain-language description (works offline)."""
        packs = self._load()["packs"]
        q = {}
        for t in _tokens(query):
            if t in self._idf:
                q[t] = q.get(t, 0) + self._idf[t]
        norm = math.sqrt(sum(x * x for x in q.values())) or 1
        raw = set(re.findall(r"[a-z0-9]+", query.lower()))
        boost = {sec for sec, hints in _HINTS.items() if raw & hints}
        scored = []
        for m, v in zip(packs, self._vecs):
            s = sum(w / norm * v.get(t, 0) for t, w in q.items())
            if s > 0 and m["sector"] in boost:
                s += 0.15
            if s > 0:
                scored.append((round(s, 3), m))
        scored.sort(key=lambda x: -x[0])
        return [dict(m, score=s) for s, m in scored[:k]]

    def source(self, pack_id):
        return (HOME / self.get(pack_id)["path"]).read_text(encoding="utf-8")


domains = _Domains()


def compose(request: str, k: int = 3):
    """Prompt → plan. Finds the best domain packs for a request and prepares a ready-to-run program.

    Returns dict(best, alternatives, program, inputs) where `program` is a Program and `inputs`
    maps the flow's input to the request text. Works offline; use ask() to customise with AI."""
    matches = domains.search(request, k=k + 1)
    if not matches:
        return {"best": None, "alternatives": [], "program": None, "inputs": {}}
    best = matches[0]
    prog = load(HOME / best["path"])
    return {"best": best, "alternatives": matches[1:], "program": prog,
            "inputs": {prog.inputs[0]: request} if len(prog.inputs) == 1 else {}}


def ask(request: str, current: str | None = None, client=None, log=print):
    """AI writes (or changes) an AlgoLang program; the compiler checks it and errors are repaired.

    Returns dict(source, ok, attempts, diagnostics). Needs ANTHROPIC_API_KEY unless `client` is given."""
    import algoagent
    return algoagent.write_program(request, current=current, client=client, log=log)


# ══════════════════════════════ governance ═══════════════════════════════════
class _Audit:
    verify = staticmethod(_rt.verify_audit)

    @staticmethod
    def report(directory="runs"):
        """Usage, cost and governance summary across every audit log in a folder."""
        d = Path(directory)
        out = {"programs": {}, "agents": {}, "totals": dict(calls=0, tokens=0, escalated=0, blocked=0, failed=0,
                                                            cached=0, tool_calls=0), "chains": {}}
        for f in sorted(d.glob("*.audit.jsonl")):
            out["chains"][f.name] = _rt.verify_audit(f)["ok"]
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                prog, agent = r.get("program", f.stem), r.get("agent", "?")
                for key, bucket in ((prog, out["programs"]), (f"{prog}/{agent}", out["agents"])):
                    b = bucket.setdefault(key, dict(calls=0, tokens=0, escalated=0, blocked=0, failed=0,
                                                    cached=0, conf_sum=0.0, conf_n=0))
                    st = r.get("status")
                    if st in ("ok", "escalated", "approved"):
                        b["calls"] += 1
                        b["tokens"] += r.get("tokens", 0) or 0
                        if r.get("confidence") is not None:
                            b["conf_sum"] += r["confidence"]
                            b["conf_n"] += 1
                    b["escalated"] += st == "escalated"
                    b["blocked"] += st == "blocked"
                    b["failed"] += st == "failed"
                    b["cached"] += bool(r.get("cached"))
                t = out["totals"]
                st = r.get("status")
                t["calls"] += st in ("ok", "escalated", "approved")
                t["tokens"] += r.get("tokens", 0) or 0
                t["escalated"] += st == "escalated"
                t["blocked"] += st == "blocked"
                t["failed"] += st == "failed"
                t["cached"] += bool(r.get("cached"))
                t["tool_calls"] += len(r.get("tool_calls") or [])
        for bucket in (out["programs"], out["agents"]):
            for b in bucket.values():
                b["avg_confidence"] = round(b.pop("conf_sum") / b["conf_n"], 3) if b["conf_n"] else None
                b.pop("conf_n")
        return out


class _Review:
    @staticmethod
    def pending(path=None):
        return _rt.list_reviews("pending", path)

    @staticmethod
    def all(path=None):
        return _rt.list_reviews("all", path)

    @staticmethod
    def approve(item_id, reviewer="", note="", path=None):
        return _rt.decide_review(item_id, "approved", reviewer, note, path)

    @staticmethod
    def reject(item_id, reviewer="", note="", path=None):
        return _rt.decide_review(item_id, "rejected", reviewer, note, path)


audit = _Audit()
review = _Review()
