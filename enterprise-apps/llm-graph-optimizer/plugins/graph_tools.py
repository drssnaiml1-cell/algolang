"""AlgoGraph™ tools: optimise the agent graph of an AlgoLang program across large (LLM) and small (SLM) models.

    graph.analyze   the data-flow graph of a .algo program: agents, parallel stages, decisions, critical path
    graph.optimize  the cheapest model for every agent that meets each agent's quality floor and the
                    end-to-end latency limit. Exact: branch and bound over the program's real flow graph,
                    cross-checked by brute force when the search space is small. Result says VERIFIED.
    slm.triage      a deterministic complexity score for a request: can a small model answer it?

Benchmark scores and prices in data/model_catalog.csv are illustrative. Replace them with your own eval
results and contracted prices before relying on the optimiser.
"""
from __future__ import annotations

import csv
import itertools
import re
from pathlib import Path

from algoruntime import register_tool

APP = Path(__file__).resolve().parent.parent
APPS = APP.parent                                  # programs may be analysed anywhere under enterprise-apps/
CLASSES = ("extraction", "classification", "reasoning", "writing", "review")
FLOOR = {"extraction": 0.80, "classification": 0.80, "reasoning": 0.85, "writing": 0.75, "review": 0.75}
KEYWORDS = [
    ("reasoning", r"score|assess|evaluat|decid|recommend|committee|panel|judge|risk|fraud|complian|eligib|urgency|"
                  r"optimi|plan|strateg|diagnos|triage note|analy[sz]"),
    ("writing", r"write|draft|summar|letter|memo|notice|reply|report|explain|wording|redline|referral|answer"),
    ("review", r"review|check|verify|audit|sign-off|signoff|record"),
    ("classification", r"classif|route|routing|triage|label|categor|detect|intent|complexity"),
    ("extraction", r"extract|parse|pull|lookup|look up|retriev|find|fetch|track|search|bureau|quote|intake|facts"),
]


# ───────────────────────────── catalog and graph ─────────────────────────────
def catalog(allow_slm=True):
    rows = list(csv.DictReader(open(APP / "data" / "model_catalog.csv", newline="", encoding="utf-8")))
    out = []
    for r in rows:
        if r["tier"] == "slm" and not allow_slm:
            continue
        out.append(dict(model=r["model"], tier=r["tier"], p_in=float(r["price_in_usd_per_m"]),
                        p_out=float(r["price_out_usd_per_m"]), latency=float(r["latency_s"]),
                        wh=float(r["energy_wh_per_1k"]), quality={c: float(r[c]) for c in CLASSES}))
    return out


def task_class(agent):
    """What kind of work an agent does: its name counts most, then its goal, then its role."""
    name = re.sub(r"(?<!^)(?=[A-Z])", " ", agent.name.split(".")[-1]).lower()
    score = {}
    for weight, text in ((3, name), (2, (agent.goal or "").lower()), (1, (agent.role or "").lower())):
        for cls, pat in KEYWORDS:
            score[cls] = score.get(cls, 0) + weight * len(re.findall(pat, text))
    best = max(score.values())
    if best == 0:
        return "writing"
    for cls, _pat in KEYWORDS:                       # ties: the stricter class first (reasoning, writing …)
        if score[cls] == best:
            return cls


def resolve(path_text):
    """A .algo path from the request, kept inside enterprise-apps/."""
    m = re.search(r"[\w./\\-]+\.algo\b", path_text)
    if not m:
        raise ValueError("no program (.algo path) in the request")
    p = (APP / m.group(0)).resolve()
    if not p.exists():
        p = (APPS / m.group(0)).resolve()
    if APPS.resolve() not in p.parents or not p.exists():
        raise ValueError(f"{m.group(0)}: not found under enterprise-apps/")
    return p


def load_graph(path: Path):
    """(program, agent nodes in topological order, predecessors among agent nodes, node → agent)."""
    import algoc
    prog, diags = algoc.load_program(path.read_text(encoding="utf-8"), path.name, path.parent)
    errors = [d for d in diags if str(d.code).startswith("E")]
    if errors and not prog.flows:
        raise ValueError(f"{path.name} does not compile: {errors[0]}")
    nodes, edges = algoc.flow_graph(prog)
    kind = {n[0]: n[2] for n in nodes}
    label = {n[0]: n[1] for n in nodes}
    agent_nodes = [n[0] for n in nodes if n[2] in ("agent", "par", "branch") and n[1] in prog.agents]
    raw = {}
    for a, b, _dashed in edges:
        raw.setdefault(b, set()).add(a)

    def agent_preds(n, seen=None):                 # walk back through inputs, decisions and emits
        seen = seen if seen is not None else set()
        out = set()
        for p in raw.get(n, ()):
            if p in seen:
                continue
            seen.add(p)
            if p in agent_nodes:
                out.add(p)
            elif kind.get(p) != "input":
                out |= agent_preds(p, seen)
        return out
    preds = {n: agent_preds(n) for n in agent_nodes}
    order, done = [], set()
    while len(order) < len(agent_nodes):           # topological order (flow_graph ids are already close)
        progress = False
        for n in agent_nodes:
            if n not in done and preds[n] <= done:
                order.append(n)
                done.add(n)
                progress = True
        if not progress:
            raise ValueError("the flow graph has a cycle")
    return prog, order, preds, {n: label[n] for n in agent_nodes}


def tokens(agent):
    """Rough tokens per call: prompt (role, goal, inputs, tool results) and answer."""
    t_in = (len(agent.role or "") + len(agent.goal or "")) // 4 + 300 * max(1, len(agent.params)) + 400 * len(agent.uses)
    base = agent.returns.replace("uncertain<", "").rstrip(">")
    t_out = {"score": 40, "bool": 20, "list": 180, "json": 200}.get(base, 300)
    k = int(agent.policy.get("samples", 3)) if agent.returns.startswith("uncertain<") else 1
    return t_in * k, t_out * k


# ───────────────────────────── the optimiser ─────────────────────────────
def critical_path(order, preds, lat):
    finish = {}
    for n in order:
        finish[n] = max((finish[p] for p in preds[n]), default=0.0) + lat[n]
    return max(finish.values(), default=0.0), finish


def solve(order, preds, options, limit):
    """Exact branch and bound. options[n] = [(cost, latency, choice), …]. Minimise total cost subject to
    critical-path latency <= limit. Returns (cost, {node: choice}, nodes_explored) or None if infeasible."""
    for n in order:
        options[n] = sorted(options[n], key=lambda o: (o[0], o[1]))
    min_cost = {n: min(o[0] for o in options[n]) for n in order}
    min_lat = {n: min(o[1] for o in options[n]) for n in order}
    rest_cost = [0.0] * (len(order) + 1)
    for i in range(len(order) - 1, -1, -1):
        rest_cost[i] = rest_cost[i + 1] + min_cost[order[i]]
    best = [float("inf"), None]
    explored = [0]

    def feasible(i, finish):
        """Can the unassigned nodes still finish in time, each at its fastest option?"""
        f = dict(finish)
        for n in order[i:]:
            f[n] = max((f[p] for p in preds[n]), default=0.0) + min_lat[n]
            if f[n] > limit + 1e-9:
                return False
        return True

    def go(i, cost, finish, chosen):
        explored[0] += 1
        if cost + rest_cost[i] >= best[0] - 1e-12:
            return
        if i == len(order):
            best[0], best[1] = cost, dict(chosen)
            return
        n = order[i]
        start = max((finish[p] for p in preds[n]), default=0.0)
        for c, lat, choice in options[n]:
            end = start + lat
            if end > limit + 1e-9:
                continue
            finish[n], chosen[n] = end, choice
            if feasible(i + 1, finish):
                go(i + 1, cost + c, finish, chosen)
            del finish[n], chosen[n]
    go(0, 0.0, {}, {})
    return (best[0], best[1], explored[0]) if best[1] is not None else None


def brute_force(order, preds, options, limit):
    best = None
    for combo in itertools.product(*(options[n] for n in order)):
        lat = {n: o[1] for n, o in zip(order, combo)}
        if critical_path(order, preds, lat)[0] <= limit + 1e-9:
            c = sum(o[0] for o in combo)
            if best is None or c < best - 1e-12:
                best = c
    return best


def parse_constraints(text):
    t = text.lower()
    q = re.search(r"quality\s*(?:>=|≥|at least|of)?\s*(0?\.\d+|1(?:\.0+)?)", t)
    lat = re.search(r"latency\s*(?:<=|≤|under|below|within|of)?\s*(\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?", t)
    return dict(quality=float(q.group(1)) if q else None, latency=float(lat.group(1)) if lat else 30.0,
                allow_slm=not re.search(r"cloud only|no (?:local|slm|small)", t))


def optimise(path_text, constraints_text=""):
    path = resolve(path_text)
    cons = parse_constraints(constraints_text or path_text)
    prog, order, preds, label = load_graph(path)
    models = catalog(cons["allow_slm"])
    options, needs, meta = {}, {}, {}
    for n in order:
        a = prog.agents[label[n]]
        cls = task_class(a)
        need = FLOOR[cls] if cons["quality"] is None else max(FLOOR[cls], cons["quality"])
        if a.returns.endswith("score>") or a.returns == "score" or a.policy.get("human_below") is not None \
                or a.policy.get("approvals") or a.policy.get("human_always"):
            need += 0.05                           # agents that decide, or whose results people review
        need = round(min(need, 0.97), 2)
        t_in, t_out = tokens(a)
        opts = []
        for m in models:
            if m["quality"][cls] + 1e-9 >= need:
                cost = (t_in * m["p_in"] + t_out * m["p_out"]) / 1e6
                opts.append((round(cost, 8), m["latency"] * (1 if not a.returns.startswith("uncertain<") else 1.0), m["model"]))
        if not opts:
            return (f"INFEASIBLE: agent {a.name} ({cls}) needs quality {need:.2f}, which no model in the catalog "
                    f"reaches. Lower the floor or add a stronger model.")
        options[n], needs[n], meta[n] = opts, need, (a, cls, t_in, t_out)
    res = solve(order, preds, {n: list(o) for n, o in options.items()}, cons["latency"])
    if res is None:
        fastest = critical_path(order, preds, {n: min(o[1] for o in options[n]) for n in order})[0]
        return (f"INFEASIBLE: even the fastest models that meet every quality floor need {fastest:.1f} s on the "
                f"critical path, above the limit of {cons['latency']:.1f} s. Raise the limit or parallelise the flow.")
    cost, choice, explored = res
    space = 1
    for n in order:
        space *= len(options[n])
    check = ""
    if space <= 250_000:
        bf = brute_force(order, preds, options, cons["latency"])
        if bf is None or abs(bf - cost) > 1e-9:
            return f"ERROR: branch and bound ({cost}) and brute force ({bf}) disagree. Do not use this result."
        check = f"; brute force over {space:,} combinations agrees"
    by = {m["model"]: m for m in models}
    top = max(models, key=lambda m: m["quality"]["reasoning"])
    lat = {n: by[choice[n]]["latency"] for n in order}
    cp, _ = critical_path(order, preds, lat)
    base_cost = sum((meta[n][2] * top["p_in"] + meta[n][3] * top["p_out"]) / 1e6 for n in order)
    base_cp, _ = critical_path(order, preds, {n: top["latency"] for n in order})
    wh = sum((meta[n][2] + meta[n][3]) / 1000 * by[choice[n]]["wh"] for n in order)
    base_wh = sum((meta[n][2] + meta[n][3]) / 1000 * top["wh"] for n in order)
    slm = sum(1 for n in order if by[choice[n]]["tier"] == "slm")
    saving = (1 - cost / base_cost) * 100 if base_cost else 0.0
    lines = [f"VERIFIED optimal model assignment for {path.stem} (exhaustive branch and bound, {explored:,} nodes "
             f"explored{check})",
             f"cost per request ${cost:.5f} vs ${base_cost:.5f} with {top['model']} everywhere ({saving:.0f}% lower) · "
             f"critical path {cp:.1f} s (limit {cons['latency']:.1f} s; all-{top['model']} {base_cp:.1f} s) · "
             f"energy {wh:.3f} Wh vs {base_wh:.3f} Wh",
             f"small models: {slm} of {len(order)} agents run on SLMs",
             "agent | task | needs | model | quality | $ per request | latency s"]
    for n in order:
        a, cls, t_in, t_out = meta[n]
        m = by[choice[n]]
        lines.append(f"{a.name} | {cls} | {needs[n]:.2f} | {m['model']} | {m['quality'][cls]:.2f} | "
                     f"{(t_in * m['p_in'] + t_out * m['p_out']) / 1e6:.5f} | {m['latency']:.1f}")
    pairs = ", ".join(f'"{meta[n][0].name}": "{choice[n]}"' for n in order)
    lines.append('apply without editing the program, in algo.config.json: "agent_models": {' + pairs + "}")
    return "\n".join(lines)


def analyse(path_text):
    path = resolve(path_text)
    prog, order, preds, label = load_graph(path)
    lat = {n: 1.0 for n in order}
    cp, finish = critical_path(order, preds, lat)
    end = max(finish, key=finish.get) if finish else None
    chain = []
    while end is not None:
        chain.append(label[end])
        ps = [p for p in preds[end] if abs(finish[p] - (finish[end] - 1.0)) < 1e-9]
        end = ps[0] if ps else None
    par = sum(1 for n in order if len(preds[n]) == 0 or any(len(set(preds[n]) & set(preds[m])) and preds[n] == preds[m]
                                                           for m in order if m != n))
    classes = {}
    for n in order:
        c = task_class(prog.agents[label[n]])
        classes[c] = classes.get(c, 0) + 1
    t = sum(sum(tokens(prog.agents[label[n]])) for n in order)
    gated = sum(1 for n in order if prog.agents[label[n]].policy.get("human_below") is not None
                or prog.agents[label[n]].policy.get("approvals") or prog.agents[label[n]].policy.get("human_always"))
    return (f"graph of {path.stem}: {len(order)} agents, {par} can run in parallel with a sibling, "
            f"{gated} with human review, critical path {int(cp)} agents: {' → '.join(reversed(chain))}. "
            f"Task classes: {', '.join(f'{k} {v}' for k, v in sorted(classes.items()))}. "
            f"About {t:,} tokens per request.")


# ───────────────────────────── triage ─────────────────────────────
CUES = r"\b(why|compare|analy[sz]e|plan|strategy|legal|contract|regulat\w*|diagnos\w*|calculate|trade-?off|evaluate|" \
       r"risk|negotiat\w*|explain|assess)\b"


def complexity(text):
    words = len(text.split())
    cues = re.findall(CUES, text.lower())
    score = 0.0
    why = []
    if words > 40:
        score += 0.25 if words <= 80 else 0.35
        why.append(f"{words} words")
    nums = len(re.findall(r"\d[\d,.%]*", text))
    if nums >= 4:
        score += 0.15
        why.append(f"{nums} figures")
    if cues:
        score += min(0.6, 0.15 * len(set(cues)))       # three or more cues: complex on their own
        why.append(f"reasoning cues: {', '.join(sorted(set(cues)))}")
    if text.count("?") >= 2:
        score += 0.1
        why.append("several questions")
    return round(min(score, 1.0), 2), why


@register_tool("slm.triage", "Complexity of a request: SIMPLE (a small model can answer) or COMPLEX (route to a large model)")
def triage(query: str) -> str:
    text = query.split("request:", 1)[1] if "request:" in query else query    # the agent's goal ends "request: …"
    score, why = complexity(text)
    if score >= 0.5:
        return f"COMPLEX (score {score:.2f}): {'; '.join(why)}. Route to a large model."
    return f"SIMPLE (score {score:.2f}){': ' + '; '.join(why) if why else ''}. A small model can answer."


@register_tool("graph.analyze", "Data-flow graph of an AlgoLang program: agents, parallel stages, critical path, tokens")
def analyze_tool(query: str) -> str:
    try:
        return analyse(query)
    except ValueError as e:
        return f"cannot analyse: {e}"


@register_tool("graph.optimize", "Cheapest LLM/SLM model for every agent of a program within quality floors and a latency limit")
def optimize_tool(query: str) -> str:
    try:
        return optimise(query)
    except ValueError as e:
        return f"INFEASIBLE: {e}"
