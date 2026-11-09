"""AlgoRL Control Room™ tools: safe reinforcement learning for battery dispatch in a campus microgrid.

The environment is a finite Markov decision process: each hour the controller charges, idles or discharges
a battery; the grid supplies whatever load the solar panels and battery do not. Rewards are money (INR):
selling at peak prices earns, buying costs, and every MWh cycled through the battery wears it out.

    rl.train      tabular Q-learning (ε-greedy, seeded). With the safety shield on, actions that would
                  break the grid-import cap are masked during learning and execution.
    rl.evaluate   the learned policy against the exact optimum (finite-horizon value iteration), a
                  time-of-day rule and doing nothing, on the same 1,000 simulated days
    rl.stress     the same policies on heatwave days only: higher load and prices, the hardest case

All data is synthetic (data/microgrid.json).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

from algoruntime import register_tool

DATA = Path(__file__).resolve().parent.parent / "data"
ACTIONS = (-1, 0, 1)                      # discharge one step, idle, charge one step
H = 24


@lru_cache(maxsize=1)
def grid():
    return json.loads((DATA / "microgrid.json").read_text(encoding="utf-8"))


def day_profile(kind, rng=None):
    g = grid()
    d = g["day_types"][kind]
    hours = np.arange(H)
    solar = np.clip(np.sin((hours - 6) / 12 * np.pi), 0, None) * d["solar_peak_mw"]
    load = np.array(g["load_mw"]) * d["load_scale"]
    price = np.array(g["price_inr_per_mwh"], dtype=float) * d["price_scale"]
    if rng is not None:                       # weather and market noise on simulated days
        solar = solar * rng.uniform(0.85, 1.15)
        load = load * rng.normal(1, 0.03, H)
        price = price * rng.normal(1, 0.05, H)
    return solar, load, price


def step(soc, a, h, solar, load, price):
    """One hour. Returns (next soc, reward INR, grid import MW, feasible)."""
    g = grid()
    nxt = soc + a
    if not 0 <= nxt < g["levels"]:
        return soc, -1e9, 0.0, False
    e = g["step_mwh"]
    if a > 0:                                             # charging draws more than it stores
        battery = e / g["efficiency"]
    elif a < 0:                                           # discharging delivers less than it releases
        battery = -e * g["efficiency"]
    else:
        battery = 0.0
    net = load[h] - solar[h] + battery                    # MW for one hour = MWh
    cost = net * price[h] if net > 0 else net * price[h] * g["export_price_factor"]
    wear = abs(a) * e * g["degradation_inr_per_mwh"]
    return nxt, -(cost + wear), max(net, 0.0), True


def shielded(soc, h, solar, load, price):
    """Actions allowed by the safety shield: keep the charge level valid and grid import within the cap."""
    cap = grid()["import_cap_mw"]
    ok = []
    for i, a in enumerate(ACTIONS):
        _, _, imp, feas = step(soc, a, h, solar, load, price)
        if feas and imp <= cap + 1e-9:
            ok.append(i)
    if not ok:                                           # nothing satisfies the cap: least import wins
        ok = [min((i for i, a in enumerate(ACTIONS) if step(soc, a, h, solar, load, price)[3]),
                  key=lambda i: step(soc, ACTIONS[i], h, solar, load, price)[2])]
    return ok


def mean_profile():
    g = grid()
    parts = [(d["p"], day_profile(k)) for k, d in g["day_types"].items()]
    return tuple(sum(p * x[i] for p, x in parts) for i in range(3))


@lru_cache(maxsize=2)
def value_iteration(shield=True):
    """Exact optimal policy for the expected day (backward induction over hour × charge level)."""
    g = grid()
    solar, load, price = mean_profile()
    V = np.zeros((H + 1, g["levels"]))
    pi = np.zeros((H, g["levels"]), dtype=int)
    for h in range(H - 1, -1, -1):
        for s in range(g["levels"]):
            allowed = shielded(s, h, solar, load, price) if shield else range(len(ACTIONS))
            best, arg = -np.inf, 1
            for i in allowed:
                n, r, _, feas = step(s, ACTIONS[i], h, solar, load, price)
                if feas and r + V[h + 1, n] > best:
                    best, arg = r + V[h + 1, n], i
            V[h, s], pi[h, s] = best, arg
    return pi


@lru_cache(maxsize=8)
def q_learning(shield=True, episodes=3000, seed=11):
    g = grid()
    rng = np.random.default_rng(seed)
    kinds = list(g["day_types"])
    probs = np.array([g["day_types"][k]["p"] for k in kinds])
    Q = np.zeros((H, g["levels"], len(ACTIONS)))
    cap = g["import_cap_mw"]
    curve = []
    for ep in range(episodes):
        eps = max(0.05, 1 - ep / (0.7 * episodes))
        alpha = max(0.05, 0.5 * (1 - ep / episodes))
        solar, load, price = day_profile(kinds[rng.choice(len(kinds), p=probs)], rng)
        s, total = g["levels"] // 2, 0.0
        for h in range(H):
            allowed = shielded(s, h, solar, load, price) if shield else \
                [i for i, a in enumerate(ACTIONS) if 0 <= s + a < g["levels"]]
            i = int(rng.choice(allowed)) if rng.random() < eps else max(allowed, key=lambda j: Q[h, s, j])
            n, r, imp, _ = step(s, ACTIONS[i], h, solar, load, price)
            idle = step(s, 0, h, solar, load, price)[1]
            gain = r - idle                                    # reward relative to idling keeps Q-values near 0
            if shield and imp > cap + 1e-9:
                gain -= 20000                                  # safe RL: a cap breach is heavily penalised
            nxt_ok = [j for j, a2 in enumerate(ACTIONS) if 0 <= n + a2 < g["levels"]]
            future = 0.0 if h == H - 1 else max(Q[h + 1, n, j] for j in nxt_ok)
            Q[h, s, i] += alpha * (gain + future - Q[h, s, i])
            s, total = n, total + r
        curve.append(total)
    valid = np.array([[[0 <= s + a < g["levels"] for a in ACTIONS] for s in range(g["levels"])]] * H)
    return np.where(valid, Q, -np.inf).argmax(axis=2), tuple(float(np.mean(curve[k:k + max(1, episodes // 10)]))
                                    for k in range(0, episodes, max(1, episodes // 10)))


def run(policy, kinds, n=1000, seed=99, shield_exec=False):
    """Mean daily profit, cap violations and worst day over n simulated days."""
    g = grid()
    rng = np.random.default_rng(seed)
    probs = np.array([g["day_types"][k]["p"] for k in kinds])
    probs = probs / probs.sum()
    profits, violations, unavoidable, worst = [], 0, 0, 0.0
    cap = g["import_cap_mw"]
    for _ in range(n):
        solar, load, price = day_profile(kinds[rng.choice(len(kinds), p=probs)], rng)
        s, total = g["levels"] // 2, 0.0
        for h in range(H):
            i = policy(h, s, solar, load, price)
            if shield_exec and i not in shielded(s, h, solar, load, price):
                i = shielded(s, h, solar, load, price)[0]
            n_, r, imp, feas = step(s, ACTIONS[i], h, solar, load, price)
            if not feas:
                i, (n_, r, imp, _) = 1, step(s, 0, h, solar, load, price)
            if imp > cap + 1e-9:
                safe_exists = any(step(s, a, h, solar, load, price)[3] and step(s, a, h, solar, load, price)[2] <= cap + 1e-9
                                  for a in ACTIONS)
                if safe_exists:
                    violations += 1                      # the policy could have stayed under the cap
                else:
                    unavoidable += 1                     # no action could: load exceeded cap + battery power
            
            worst = max(worst, imp)
            s, total = n_, total + r
        profits.append(total)
    return float(np.mean(profits)), violations, worst, unavoidable


def policies(shield, episodes):
    g = grid()
    learned, _ = q_learning(shield, episodes)
    opt = value_iteration(True)
    peak = [h for h in range(H) if g["price_inr_per_mwh"][h] >= 7000]
    cheap = [h for h in range(H) if g["price_inr_per_mwh"][h] <= 3100]

    def rule(h, s, *_):
        return 2 if h in cheap and s < g["levels"] - 1 else (0 if h in peak and s > 0 else 1)
    return {                                      # name: (policy, run through the safety shield?)
        "learned (Q-learning)": (lambda h, s, *_: int(learned[h, s]), shield),
        "exact optimum (value iteration)": (lambda h, s, *_: int(opt[h, s]), True),
        "time-of-day rule": (rule, False),
        "do nothing": (lambda *_: 1, False),
    }


def options(query):
    q = query.lower()
    shield = not ("without" in q and "shield" in q) and "unshielded" not in q
    m = re.search(r"(\d[\d,]*)\s*episodes", q)
    episodes = int(m.group(1).replace(",", "")) if m else 3000
    return shield, max(10, min(episodes, 20000))


def table(shield, episodes, kinds, title):
    res = {}
    for name, (fn, sh) in policies(shield, episodes).items():
        res[name] = run(fn, kinds, shield_exec=sh)
    base = res["do nothing"][0]
    opt = res["exact optimum (value iteration)"][0]
    lines = []
    for name, (p, v, w, _u) in res.items():
        gap = "" if name.startswith("exact") else f"  ({100 * (opt - p) / abs(opt - base):.0f}% of the optimum's gain missed)" \
            if opt != base else ""
        lines.append(f"  {name:<32} ₹{p - base:>9,.0f}/day vs doing nothing · {v} avoidable cap violations{gap}")
    u = res["exact optimum (value iteration)"][3]
    if u:
        lines.append(f"  ({u} hour(s) exceeded the cap even at full discharge: load above cap + battery power; "
                     f"not counted against any policy)")
    return res, lines


@register_tool("rl.train", "Train a battery dispatch policy with tabular Q-learning (safety shield on or off)")
def rl_train(query: str) -> str:
    shield, episodes = options(query)
    _, curve = q_learning(shield, episodes)
    g = grid()
    states = H * g["levels"]
    return (f"TRAINED Q-learning policy, safety shield {'ON' if shield else 'OFF'}: {episodes:,} simulated days, "
            f"{states} states × {len(ACTIONS)} actions, seed 11\n"
            f"learning curve (mean daily reward by tenth of training, ₹): " + " → ".join(f"{c:,.0f}" for c in curve))


@register_tool("rl.evaluate", "Evaluate the learned policy against the exact optimum and baselines on 1,000 simulated days")
def rl_evaluate(query: str) -> str:
    shield, episodes = options(query)
    kinds = list(grid()["day_types"])
    res, lines = table(shield, episodes, kinds, "all days")
    lp, lv, _, _ = res["learned (Q-learning)"]
    rp = res["time-of-day rule"][0]
    if lv:
        head = (f"UNSAFE: the learned policy broke the {grid()['import_cap_mw']} MW import cap {lv} times in 1,000 days "
                f"when a safe action existed")
    elif lp > rp:
        head = f"SAFE AND BEATS BASELINE: learned policy earns ₹{lp - rp:,.0f}/day more than the time-of-day rule, no cap violations"
    else:
        head = f"SAFE BUT WEAKER: learned policy earns ₹{rp - lp:,.0f}/day less than the time-of-day rule; train longer"
    return head + "\n" + "\n".join(lines)


@register_tool("rl.stress", "Stress-test the dispatch policies on heatwave days only")
def rl_stress(query: str) -> str:
    shield, episodes = options(query)
    res, lines = table(shield, episodes, ["heatwave"], "heatwave")
    v = res["learned (Q-learning)"][1]
    head = (f"STRESS FAIL: {v} avoidable import-cap violations on 1,000 heatwave days" if v
            else "STRESS PASS: no avoidable import-cap violations on 1,000 heatwave days")
    return head + "\n" + "\n".join(lines)
