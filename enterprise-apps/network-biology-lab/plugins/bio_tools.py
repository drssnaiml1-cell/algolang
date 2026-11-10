"""AlgoBio Network Lab™ tools: computational and network biology on a synthetic protein interaction network.

    net.centrality  degree and betweenness centrality (Brandes' algorithm on 400 sampled sources, seeded):
                    hubs and bottlenecks, and where the disease seed proteins sit
    net.modules     communities by label propagation (seeded), with Newman's modularity Q, and the module
                    holding most disease seeds
    net.propagate   disease-gene prioritisation by random walk with restart from the seed proteins; validated by
                    hiding known disease proteins and measuring how many reappear in the top 100 (and AUROC)
    bio.enrich      pathway enrichment of the top candidates: hypergeometric test, Benjamini–Hochberg FDR
    bio.sequence    GC content, the longest open reading frame on six frames, most common 3-mers

Data (data/network.json): 1,500 proteins, 12 planted modules, a 40-protein disease module of which 28 are
known seeds and 12 are held out for validation; 40 pathways. All identifiers are synthetic (BP####, PW-##).
"""
from __future__ import annotations

import json
import math
import random
import re
from collections import Counter, defaultdict, deque
from functools import lru_cache
from pathlib import Path

from algoruntime import register_tool

DATA = Path(__file__).resolve().parent.parent / "data"
TOP = 100


@lru_cache(maxsize=1)
def net():
    d = json.loads((DATA / "network.json").read_text(encoding="utf-8"))
    adj = defaultdict(set)
    for a, b in d["edges"]:
        adj[a].add(b)
        adj[b].add(a)
    return d, dict(adj)


@lru_cache(maxsize=1)
def betweenness(samples=400, seed=5):
    """Brandes' betweenness, estimated from `samples` source nodes and scaled to the full graph."""
    _d, adj = net()
    nodes = sorted(adj)
    srcs = random.Random(seed).sample(nodes, min(samples, len(nodes)))
    bc = dict.fromkeys(nodes, 0.0)
    for s in srcs:
        stack, pred, sigma, dist = [], defaultdict(list), dict.fromkeys(nodes, 0), dict.fromkeys(nodes, -1)
        sigma[s], dist[s] = 1, 0
        q = deque([s])
        while q:
            v = q.popleft()
            stack.append(v)
            for w in adj[v]:
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    q.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)
        delta = dict.fromkeys(nodes, 0.0)
        while stack:
            w = stack.pop()
            for v in pred[w]:
                delta[v] += sigma[v] / sigma[w] * (1 + delta[w])
            if w != s:
                bc[w] += delta[w]
    scale = len(nodes) / len(srcs) / ((len(nodes) - 1) * (len(nodes) - 2))
    return {n: v * scale for n, v in bc.items()}


@register_tool("net.centrality", "Hubs and bottlenecks of the protein interaction network (degree, betweenness)")
def net_centrality(query: str) -> str:
    d, adj = net()
    bc = betweenness()
    deg = {n: len(v) for n, v in adj.items()}
    hubs = sorted(deg, key=lambda n: -deg[n])[:5]
    bott = sorted(bc, key=lambda n: -bc[n])[:5]
    seeds = d["seeds"]
    rank = {n: i for i, n in enumerate(sorted(bc, key=lambda n: -bc[n]))}
    in_top = sum(1 for s in seeds if rank[s] < len(rank) // 10)
    return (f"NETWORK {len(adj):,} proteins · {len(d['edges']):,} interactions · mean degree "
            f"{2 * len(d['edges']) / len(adj):.1f}\n"
            f"hubs (degree): " + ", ".join(f"{n} ({deg[n]})" for n in hubs) + "\n"
            f"bottlenecks (betweenness, 400 sampled sources): " + ", ".join(f"{n} ({bc[n]:.4f})" for n in bott) + "\n"
            f"{in_top} of {len(seeds)} disease seeds are in the top 10% by betweenness")


@lru_cache(maxsize=1)
def communities(seed=3):
    _d, adj = net()
    nodes = sorted(adj)
    label = {n: i for i, n in enumerate(nodes)}
    rng = random.Random(seed)
    for _ in range(30):
        order = nodes[:]
        rng.shuffle(order)
        changed = 0
        for n in order:
            c = Counter(label[m] for m in adj[n])
            best = max(c.values())
            choice = min(k for k, v in c.items() if v == best)
            if choice != label[n]:
                label[n], changed = choice, changed + 1
        if not changed:
            break
    groups = defaultdict(list)
    for n, lab in label.items():
        groups[lab].append(n)
    return list(groups.values()), label


def modularity(groups, adj):
    m = sum(len(v) for v in adj.values()) / 2
    q = 0.0
    for g in groups:
        s = set(g)
        inside = sum(1 for a in g for b in adj[a] if b in s) / 2
        degsum = sum(len(adj[a]) for a in g)
        q += inside / m - (degsum / (2 * m)) ** 2
    return q


@register_tool("net.modules", "Communities in the interaction network (label propagation) and the disease module")
def net_modules(query: str) -> str:
    d, adj = net()
    groups, label = communities()
    big = sorted((g for g in groups if len(g) >= 5), key=len, reverse=True)
    q = modularity(groups, adj)
    seeds = set(d["seeds"])
    best = max(big, key=lambda g: len(seeds & set(g)))
    return (f"MODULES {len(big)} communities of 5+ proteins · modularity Q {q:.3f} (label propagation, seed 3)\n"
            f"sizes: {', '.join(str(len(g)) for g in big[:12])}{' …' if len(big) > 12 else ''}\n"
            f"disease module: {len(seeds & set(best))} of {len(seeds)} seeds fall in one community of {len(best)} proteins")


def rwr(seeds, restart=0.3, iters=60):
    _d, adj = net()
    nodes = sorted(adj)
    p0 = {n: (1 / len(seeds) if n in seeds else 0.0) for n in nodes}
    p = dict(p0)
    for _ in range(iters):
        nxt = dict.fromkeys(nodes, 0.0)
        for n, val in p.items():
            if val:
                share = val / len(adj[n])
                for m in adj[n]:
                    nxt[m] += share
        p = {n: (1 - restart) * nxt[n] + restart * p0[n] for n in nodes}
    return p


def seed_set(control=False):
    """The 28 known disease proteins, or, as a negative control, 28 random proteins outside the disease module."""
    d, adj = net()
    if not control:
        return frozenset(d["seeds"])
    known = set(d["seeds"]) | set(d["held_out"])
    return frozenset(random.Random(13).sample(sorted(n for n in adj if n not in known), len(d["seeds"])))


def is_control(query):
    return bool(re.search(r"negative control|random seeds|shuffled", query.lower()))


@lru_cache(maxsize=2)
def prioritised(control=False):
    d, _adj = net()
    seeds = set(seed_set(control))
    p = rwr(seeds)
    ranked = [n for n in sorted(p, key=lambda n: -p[n]) if n not in seeds]
    held = set(d["held_out"])
    hits = sum(1 for n in ranked[:TOP] if n in held)
    pos = {n: i for i, n in enumerate(ranked)}
    neg = [n for n in ranked if n not in held]
    auc = sum(1 for h in held for g in neg if pos[h] < pos[g]) / (len(held) * len(neg))
    return ranked, hits, len(held), auc


@register_tool("net.propagate", "Prioritise candidate disease proteins by random walk with restart, with held-out validation")
def net_propagate(query: str) -> str:
    control = is_control(query)
    ranked, hits, n_held, auc = prioritised(control)
    strength = "STRONG EVIDENCE" if hits / n_held >= 0.5 and auc >= 0.85 else "WEAK EVIDENCE"
    what = "28 RANDOM proteins (negative control)" if control else "28 known disease proteins"
    return (f"{strength}: {hits} of {n_held} hidden disease proteins recovered in the top {TOP} candidates · AUROC {auc:.3f}\n"
            f"random walk with restart (restart 0.3, 60 iterations) from {what}\n"
            f"top candidates: {', '.join(ranked[:12])}")


def log_comb(n, k):
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def hypergeom_sf(k, M, n, N):
    """P(X >= k) for X ~ Hypergeometric(population M, n successes, N draws)."""
    total = 0.0
    for x in range(k, min(n, N) + 1):
        total += math.exp(log_comb(n, x) + log_comb(M - n, N - x) - log_comb(M, N))
    return min(1.0, total)


@register_tool("bio.enrich", "Pathway enrichment of the top candidates (hypergeometric test, Benjamini–Hochberg FDR)")
def bio_enrich(query: str) -> str:
    d, adj = net()
    control = is_control(query)
    ranked, *_ = prioritised(control)
    genes = set(ranked[:TOP]) | set(seed_set(control))
    M = len(adj)
    rows = []
    for pid, members in d["pathways"].items():
        mem = set(members)
        k = len(genes & mem)
        p = hypergeom_sf(k, M, len(mem), len(genes)) if k else 1.0
        rows.append([pid, k, len(mem), p])
    rows.sort(key=lambda r: r[3])
    m = len(rows)
    q_prev = 1.0
    for i in range(m - 1, -1, -1):                       # Benjamini–Hochberg step-up
        q_prev = min(q_prev, rows[i][3] * m / (i + 1))
        rows[i].append(q_prev)
    sig = [r for r in rows if r[4] < 0.05]
    names = d["pathway_names"]
    head = (f"ENRICHED {len(sig)} pathway(s) at FDR < 0.05" if sig else "NO ENRICHED PATHWAY at FDR < 0.05")
    return head + f" among {len(genes)} candidate + seed proteins\n" + "\n".join(
        f"  {r[0]} {names[r[0]]:<28} {r[1]:>3}/{r[2]:<3} p {r[3]:.2e}  q {r[4]:.2e}" for r in rows[:5])


@register_tool("bio.sequence", "GC content, longest open reading frame (6 frames) and common 3-mers of a sequence (SEQ-##)")
def bio_sequence(query: str) -> str:
    d, _ = net()
    m = re.search(r"SEQ-\d{2}", query.upper())
    sid = m.group(0) if m and m.group(0) in d["sequences"] else "SEQ-01"
    s = d["sequences"][sid]
    comp = s.translate(str.maketrans("ACGT", "TGCA"))[::-1]
    best = (0, None)
    for strand, seq in (("+", s), ("-", comp)):
        for f in range(3):
            i = f
            while i + 3 <= len(seq):
                if seq[i:i + 3] == "ATG":
                    j = i
                    while j + 3 <= len(seq) and seq[j:j + 3] not in ("TAA", "TAG", "TGA"):
                        j += 3
                    if j + 3 <= len(seq) and (j - i) // 3 > best[0]:
                        best = ((j - i) // 3, f"{strand}{f + 1} at {i + 1}-{j + 3}")
                    i = j
                i += 3
    gc = (s.count("G") + s.count("C")) / len(s)
    kmers = Counter(s[i:i + 3] for i in range(len(s) - 2)).most_common(3)
    orf = f"longest ORF {best[0]} codons on frame {best[1]}" if best[1] else "no complete ORF"
    verdict = "LIKELY PROTEIN-CODING (an ORF of 150+ codons)" if best[0] >= 150 else \
        "PROBABLY NON-CODING (no ORF of 150+ codons)"
    return (f"SEQUENCE {sid} {verdict}: {len(s):,} bp · GC {gc:.1%} · {orf} · common 3-mers "
            + ", ".join(f"{k} ×{v}" for k, v in kmers))
