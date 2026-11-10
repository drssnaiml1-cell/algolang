"""AlgoMove Transport Network Optimizer™ tools: incident rerouting, signal timing, travel demand and bus service.

    traffic.reroute  Dijkstra shortest travel time on a 1,600-junction road network (6,240 directed links, travel
                     times with congestion), before and after an incident closes links; the detour and its delay
    signal.retime    Webster's method for the signalised junctions on the detour after the diverted traffic is added:
                     flow ratios y = q/s, lost time L, optimal cycle C0 = (1.5L + 5) / (1 - Y), green splits, and
                     Webster's uniform delay; Y >= 0.9 means the junction is oversaturated. Without an incident, the
                     whole city's 576 signals are retimed and compared with the fixed 120 s plan
    demand.od        morning-peak trips between 48 zones: a doubly constrained gravity model (exponential deterrence on
                     shortest travel time) balanced by Furness iteration
    transit.headway  12 bus routes: peak-direction load from the trip matrix, the headway that carries it at 85% of
                     capacity, the buses each route needs (round trip / headway), against the 320-bus fleet

Data (data/): roads.json (grid network, three incidents), junctions.csv (576 signals: flows and saturation flows),
city_zones.json (48 zones, 12 routes). All synthetic.
"""
from __future__ import annotations

import csv
import heapq
import json
import math
import re
from functools import lru_cache
from pathlib import Path

from algoruntime import register_tool

DATA = Path(__file__).resolve().parent.parent / "data"
LOST_PER_PHASE, PHASES, FIXED_CYCLE = 4.0, 2, 120.0


@lru_cache(maxsize=1)
def roads():
    d = json.loads((DATA / "roads.json").read_text(encoding="utf-8"))
    adj = {}
    names = {}
    for a, b, t, _lanes, name in d["edges"]:
        adj.setdefault(a, []).append((b, t))
        adj.setdefault(b, []).append((a, t))
        names[frozenset((a, b))] = name
    return d, adj, names


def dijkstra(adj, src, closed=frozenset()):
    dist, prev = {src: 0.0}, {}
    pq = [(0.0, src)]
    while pq:
        du, u = heapq.heappop(pq)
        if du > dist[u]:
            continue
        for v, t in adj[u]:
            if frozenset((u, v)) in closed:
                continue
            nd = du + t
            if nd < dist.get(v, math.inf):
                dist[v], prev[v] = nd, u
                heapq.heappush(pq, (nd, v))
    return dist, prev


def path(prev, src, dst):
    out = [dst]
    while out[-1] != src:
        out.append(prev[out[-1]])
    return out[::-1]


def incident_of(query):
    m = re.search(r"INC-\d{2}", query.upper())
    d, _adj, _n = roads()
    return (m.group(0), d["incidents"][m.group(0)]) if m and m.group(0) in d["incidents"] else (None, None)


@lru_cache(maxsize=4)
def detour(inc_id):
    d, adj, names = roads()
    inc = d["incidents"][inc_id]
    closed = frozenset(frozenset(e) for e in inc["closed"])
    base, prev0 = dijkstra(adj, inc["from"])
    after, prev1 = dijkstra(adj, inc["from"], closed)
    p0, p1 = path(prev0, inc["from"], inc["to"]), path(prev1, inc["from"], inc["to"])
    via = []
    for a, b in zip(p1, p1[1:]):
        n = names[frozenset((a, b))]
        if n != "local street" and (not via or via[-1] != n):
            via.append(n)
    return dict(inc=inc, before=base[inc["to"]], after=after[inc["to"]], p0=p0, p1=p1, via=via)


@register_tool("traffic.reroute", "Shortest-time detour around a road incident (INC-##), Dijkstra on the city road network")
def traffic_reroute(query: str) -> str:
    inc_id, inc = incident_of(query)
    d, adj, _ = roads()
    if inc is None:
        return f"NO INCIDENT given (INC-##): network of {len(adj):,} junctions and {2 * len(d['edges']):,} directed links is open"
    r = detour(inc_id)
    extra = r["after"] - r["before"]
    head = "MAJOR DELAY" if extra >= 3 else "MINOR DELAY"
    return (f"{head}: {inc_id} {inc['what']} adds {extra:.1f} min ({r['before']:.1f} → {r['after']:.1f} min "
            f"from {inc['from']} to {inc['to']}) · {inc['flow']:,} vehicles/h diverted\n"
            f"detour via {', '.join(r['via'][:5]) or 'local streets'} · {len(r['p1']) - 1} links · "
            f"Dijkstra on {len(adj):,} junctions, {2 * len(d['edges']):,} directed links")


@lru_cache(maxsize=1)
def junctions():
    with open(DATA / "junctions.csv", encoding="utf-8") as f:
        return {r["junction"]: {k: float(v) for k, v in r.items() if k != "junction"} for r in csv.DictReader(f)}


def webster(j):
    """Optimal cycle, greens and average uniform delay (s/veh) for a two-phase junction."""
    ys = [j["ew_flow"] / j["ew_sat"], j["ns_flow"] / j["ns_sat"]]
    Y = sum(ys)
    L = LOST_PER_PHASE * PHASES
    if Y >= 0.9:
        return dict(Y=Y, cycle=None, greens=None, delay=None)
    c = min(150.0, max(40.0, (1.5 * L + 5) / (1 - Y)))
    greens = [(c - L) * y / Y for y in ys]
    return dict(Y=Y, cycle=c, greens=greens, delay=uniform_delay(c, greens, ys, j))


def uniform_delay(c, greens, ys, j):
    flows = [j["ew_flow"], j["ns_flow"]]
    tot = 0.0
    for g, y, q in zip(greens, ys, flows):
        lam = g / c
        x = min(0.99, y / lam)
        tot += q * c * (1 - lam) ** 2 / (2 * (1 - lam * x))
    return tot / sum(flows)


def fixed_delay(j):
    ys = [j["ew_flow"] / j["ew_sat"], j["ns_flow"] / j["ns_sat"]]
    g = (FIXED_CYCLE - LOST_PER_PHASE * PHASES) / 2
    return uniform_delay(FIXED_CYCLE, [g, g], ys, j)


@register_tool("signal.retime", "Webster signal timing for the junctions on an incident detour (INC-##), or city-wide")
def signal_retime(query: str) -> str:
    inc_id, inc = incident_of(query)
    J = junctions()
    if inc is None:
        res = [(k, webster(j), fixed_delay(j)) for k, j in J.items()]
        ok = [x for x in res if x[1]["cycle"]]
        over = len(res) - len(ok)
        new = sum(x[1]["delay"] for x in ok) / len(ok)
        old = sum(x[2] for x in ok) / len(ok)
        return (f"SIGNALS RETIMED {len(ok)} of {len(res)} junctions · average delay {new:.1f} s/veh vs {old:.1f} s with the "
                f"fixed {FIXED_CYCLE:.0f} s plan (−{1 - new / old:.0%}) · oversaturated {over}\n"
                f"Webster: C0 = (1.5L + 5)/(1 − Y), L = {LOST_PER_PHASE * PHASES:.0f} s, greens in proportion to flow ratios")
    r = detour(inc_id)
    rows = []
    for a, b in zip(r["p1"], r["p1"][1:]):
        if b not in J:
            continue
        j = dict(J[b])
        ew = a[1:3] == b[1:3]                              # same row → east-west movement
        j["ew_flow" if ew else "ns_flow"] += inc["flow"]
        rows.append((b, webster(j)))
    over = [k for k, w in rows if w["cycle"] is None]
    head = (f"OVERSATURATED {len(over)} of {len(rows)} detour junctions even with optimal timing (Y >= 0.9)"
            if over else f"DETOUR SIGNALS RETIMED {len(rows)} junctions within capacity")
    ok = [(k, w) for k, w in rows if w["cycle"]][:4]
    return (head + f" · {inc['flow']:,} diverted vehicles/h added\n"
            + (f"oversaturated: {', '.join(over[:6])}\n" if over else "")
            + "retimed: " + ", ".join(f"{k} cycle {w['cycle']:.0f} s, greens {w['greens'][0]:.0f}/{w['greens'][1]:.0f} s, "
                                      f"Y {w['Y']:.2f}" for k, w in ok))


@lru_cache(maxsize=1)
def zones():
    return json.loads((DATA / "city_zones.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def cost_matrix():
    _d, adj, _ = roads()
    zs = zones()["zones"]
    out = []
    for z in zs:
        dist, _prev = dijkstra(adj, z["node"])
        out.append([max(3.0, dist[w["node"]]) for w in zs])          # intrazonal minimum 3 minutes
    return out


@lru_cache(maxsize=2)
def trip_matrix(surge=1.0, beta=0.08):
    zs = zones()["zones"]
    O = [z["population"] * 0.42 * surge for z in zs]                 # morning-peak trips produced
    D = [z["jobs"] for z in zs]
    scale = sum(O) / sum(D)
    D = [x * scale for x in D]
    c = cost_matrix()
    f = [[math.exp(-beta * cij) for cij in row] for row in c]
    A, B = [1.0] * len(zs), [1.0] * len(zs)
    for it in range(1, 101):                                          # Furness balancing
        A = [1 / sum(B[j] * D[j] * f[i][j] for j in range(len(zs))) for i in range(len(zs))]
        B = [1 / sum(A[i] * O[i] * f[i][j] for i in range(len(zs))) for j in range(len(zs))]
        T = [[A[i] * O[i] * B[j] * D[j] * f[i][j] for j in range(len(zs))] for i in range(len(zs))]
        err = max(abs(sum(T[i]) - O[i]) / O[i] for i in range(len(zs)))
        if err < 1e-6:
            break
    return T, it, err


def surge_of(query):
    q = query.lower()
    return 1.35 if re.search(r"metro (?:disruption|shutdown|closure)|festival|bandh", q) else 1.0


@register_tool("demand.od", "Morning-peak trips between 48 zones (doubly constrained gravity model, Furness balancing)")
def demand_od(query: str) -> str:
    s = surge_of(query)
    T, it, err = trip_matrix(s)
    zs = zones()["zones"]
    c = cost_matrix()
    total = sum(map(sum, T))
    mean_t = sum(T[i][j] * c[i][j] for i in range(len(zs)) for j in range(len(zs))) / total
    pairs = sorted(((T[i][j], zs[i]["zone"], zs[j]["zone"]) for i in range(len(zs)) for j in range(len(zs)) if i != j),
                   reverse=True)[:4]
    return (f"DEMAND {total:,.0f} morning-peak trips between {len(zs)} zones · mean trip {mean_t:.1f} min"
            + (" · SURGE +35% (metro disruption or festival)" if s > 1 else "") + "\n"
            f"gravity model with exp(−0.08 × minutes) deterrence, Furness balanced in {it} iterations "
            f"(row error {err:.1e}) · largest flows: " + ", ".join(f"{a}→{b} {t:,.0f}" for t, a, b in pairs))


@register_tool("transit.headway", "Bus headways and fleet needed for 12 routes from the trip matrix")
def transit_headway(query: str) -> str:
    s = surge_of(query)
    T, _it, _err = trip_matrix(s)
    zd = zones()
    idx = {z["zone"]: k for k, z in enumerate(zd["zones"])}
    c = cost_matrix()
    per_bus = zd["bus_capacity"] * zd["load_factor"]
    need, rows = 0, []
    for rt in zd["routes"]:
        st = [idx[z] for z in rt["zones"]]
        loads = []                                            # peak-direction load on each segment of the route
        for k in range(len(st) - 1):
            loads.append(sum(T[st[a]][st[b]] for a in range(k + 1) for b in range(k + 1, len(st))) * zd["transit_share"])
        peak = max(loads)
        headway = min(20.0, max(3.0, 60 * per_bus / peak))
        run = sum(c[st[k]][st[k + 1]] for k in range(len(st) - 1)) * 1.3
        buses = math.ceil((2 * run + 10) / headway)
        need += buses
        rows.append((rt["route"], peak, headway, buses))
    fleet = zd["fleet"]
    head = (f"FLEET SHORTFALL: the routes need {need} buses at peak, the depot has {fleet} ({need - fleet} short)" if need > fleet
            else f"SERVICE FEASIBLE: {need} of {fleet} buses at peak")
    busiest = sorted(rows, key=lambda r: -r[1])[:4]
    return (head + (" · SURGE +35%" if s > 1 else "") + "\n"
            + "busiest: " + ", ".join(f"{r[0]} {r[1]:,.0f} pass/h every {r[2]:.1f} min ({r[3]} buses)" for r in busiest)
            + f"\nheadway = 60 × {per_bus:.0f} passengers per bus / peak load (3-20 min); buses = round trip / headway")
