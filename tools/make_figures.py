"""Generate AlgoLang's animated README figures (navy and gold, pure SVG, no dependencies).

    python tools/make_figures.py          # writes docs/images/sections/*.svg and docs/images/apps/*.svg

Section figures are drawn from the specs below. Application figures are drawn *from the programs
themselves*: every flow in enterprise-apps/*/programs/*.algo is compiled, turned into its data-flow graph
(algoc.flow_graph) and laid out automatically, so a figure can never disagree with its code. Re-run the
script after you change a program; CI checks that the committed figures are up to date.

The SVGs animate with CSS and SMIL only (no scripts), so they move on GitHub, in browsers and in the
docs, and they stand still for readers who ask for reduced motion.
"""
from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "images"
W = 1280

NAVY0, NAVY1, NAVY2, CARD = "#081428", "#0e2140", "#132c55", "#0f2547"
GOLD, GOLD2, INK, SOFT, MUTED = "#c9a227", "#e9c75a", "#f4f1e8", "#c9b98a", "#9aa6c2"
GREEN, RED, BLUE = "#6cc28a", "#e0705c", "#8fd3ff"
SANS = '"Segoe UI", "Helvetica Neue", Helvetica, Arial, sans-serif'
MONO = '"SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace'


def x(s):
    return escape(str(s), {'"': "&quot;"})


def clip(s, n):
    s = str(s)
    return s if len(s) <= n else s[: max(1, n - 1)].rstrip() + "…"


def wrap(s, n, lines=2):
    words, out, cur = str(s).split(), [], ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) <= n:
            cur = f"{cur} {w}".strip()
        else:
            if cur:
                out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = clip(out[-1] + " …", n)
    return out


# ───────────────────────────── shared frame ─────────────────────────────
def frame(h, caption, title, subtitle="", body="", extra_css="", right=""):
    sub = f'<text x="40" y="96" fill="{SOFT}" font-size="16">{x(clip(subtitle, 120))}</text>' if subtitle else ""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h}" width="{W}" height="{h}" role="img" aria-label="{x(title)}">
  <title>{x(title)}</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{NAVY0}"/><stop offset=".6" stop-color="{NAVY1}"/><stop offset="1" stop-color="{NAVY2}"/></linearGradient>
    <linearGradient id="gold" x1="0" x2="1"><stop offset="0" stop-color="{GOLD2}"/><stop offset="1" stop-color="{GOLD}"/></linearGradient>
    <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M32 0H0V32" fill="none" stroke="{GOLD}" stroke-opacity=".06"/></pattern>
    <filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>
  <style>
    text {{ font-family: {SANS}; }}
    .mono {{ font-family: {MONO}; }}
    .wire {{ fill: none; stroke: {GOLD}; stroke-width: 2; stroke-dasharray: 6 6; animation: dash 1.1s linear infinite; }}
    .ctl {{ fill: none; stroke: {BLUE}; stroke-opacity: .55; stroke-width: 1.4; stroke-dasharray: 3 5; animation: dash 2.2s linear infinite; }}
    .card {{ fill: {CARD}; stroke: {GOLD}; stroke-opacity: .75; stroke-width: 1.4; }}
    .glow {{ animation: glow 3.6s ease-in-out infinite; }}
    .rise {{ animation: rise 1.2s cubic-bezier(.2,.8,.2,1) both; }}
    .fade {{ opacity: 0; animation: fade 7s ease-in-out infinite; }}
    .pulse {{ animation: pulse 2.4s ease-in-out infinite; }}
    @keyframes dash {{ to {{ stroke-dashoffset: -24; }} }}
    @keyframes glow {{ 0%, 100% {{ stroke-opacity: .35; }} 50% {{ stroke-opacity: 1; }} }}
    @keyframes rise {{ from {{ transform: translateY(12px); }} to {{ transform: none; }} }}
    @keyframes fade {{ 0%, 6% {{ opacity: 0; }} 14%, 88% {{ opacity: 1; }} 100% {{ opacity: 0; }} }}
    @keyframes pulse {{ 0%, 100% {{ opacity: .55; }} 50% {{ opacity: 1; }} }}
    {extra_css}
    @media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; }} .fade {{ opacity: 1; }} }}
  </style>
  <rect width="{W}" height="{h}" fill="url(#bg)"/>
  <rect width="{W}" height="{h}" fill="url(#grid)"/>
  <rect width="{W}" height="4" fill="url(#gold)"/>
  <text x="40" y="40" fill="{GOLD}" font-size="13" letter-spacing="2.6" font-weight="700">{x(caption.upper())}</text>
  <text x="40" y="72" fill="{INK}" font-size="26" font-weight="700">{x(clip(title, 80))}</text>
  {sub}
  {right}
{body}
  <text x="{W - 40}" y="{h - 14}" fill="{MUTED}" fill-opacity=".7" font-size="11" text-anchor="end">AlgoLang · AlgoProfessor AI R&amp;D Solutions</text>
</svg>
'''


def dot(path_id, delay=0.0, dur=1.6, color=None):
    return (f'<circle r="4.5" fill="{color or "#ffe08a"}" filter="url(#soft)"><animateMotion dur="{dur}s" '
            f'begin="{delay:.2f}s" repeatCount="indefinite"><mpath href="#{path_id}"/></animateMotion></circle>')


def badge(cx, cy, n):
    return (f'<circle cx="{cx}" cy="{cy}" r="15" fill="url(#gold)"/>'
            f'<text x="{cx}" y="{cy + 5}" fill="{NAVY1}" font-size="13.5" font-weight="800" text-anchor="middle">{x(n)}</text>')


# ───────────────────────────── layouts ─────────────────────────────
def cards(spec, cols=None):
    items = spec["items"]
    cols = cols or spec.get("cols") or min(5, len(items))
    rows = (len(items) + cols - 1) // cols
    gap, top = 18, 124 if spec.get("subtitle") else 100
    cw = (W - 80 - gap * (cols - 1)) / cols
    ch = spec.get("card_h", 118)
    h = top + rows * (ch + gap) + 30
    chars = int((cw - 34) / 7.6)
    out = []
    for i, it in enumerate(items):
        r, c = divmod(i, cols)
        x0, y0 = 40 + c * (cw + gap), top + r * (ch + gap)
        delay = (i * 0.12) % 3.6
        out.append(f'<g class="rise" style="animation-delay:{i * 0.08:.2f}s">')
        out.append(f'<rect x="{x0:.1f}" y="{y0}" width="{cw:.1f}" height="{ch}" rx="12" class="card"/>')
        out.append(f'<rect x="{x0:.1f}" y="{y0}" width="{cw:.1f}" height="{ch}" rx="12" fill="none" stroke="{GOLD2}" '
                   f'stroke-width="1.6" class="glow" style="animation-delay:{delay:.2f}s"/>')
        out.append(badge(x0 + 26, y0 + 28, it.get("n", i + 1)))
        out.append(f'<text x="{x0 + 50:.1f}" y="{y0 + 33}" fill="{INK}" font-size="16" font-weight="700">'
                   f'{x(clip(it["t"], int((cw - 62) / 8.6)))}</text>')
        for j, line in enumerate(wrap(it.get("d", ""), chars, spec.get("lines", 3))):
            out.append(f'<text x="{x0 + 18:.1f}" y="{y0 + 62 + j * 19}" fill="{SOFT}" font-size="13.5">{x(line)}</text>')
        if it.get("tag"):
            out.append(f'<text x="{x0 + cw - 14:.1f}" y="{y0 + ch - 12}" fill="{GOLD2}" font-size="12" '
                       f'text-anchor="end" class="mono">{x(it["tag"])}</text>')
        out.append("</g>")
    return frame(h, spec["caption"], spec["title"], spec.get("subtitle", ""), "\n".join(out))


def pipeline(spec):
    steps = spec["steps"]
    n = len(steps)
    top = 132 if spec.get("subtitle") else 110
    gap = 46
    bw = (W - 80 - gap * (n - 1)) / n
    bh = spec.get("box_h", 152)
    h = top + bh + (70 if spec.get("note") else 40)
    out, paths, dots = [], [], []
    for i, st in enumerate(steps):
        x0 = 40 + i * (bw + gap)
        out.append(f'<g class="rise" style="animation-delay:{i * 0.12:.2f}s">')
        out.append(f'<rect x="{x0:.1f}" y="{top}" width="{bw:.1f}" height="{bh}" rx="12" class="card"/>')
        out.append(badge(x0 + 24, top + 26, i + 1))
        out.append(f'<text x="{x0 + 46:.1f}" y="{top + 31}" fill="{INK}" font-size="15.5" font-weight="700">'
                   f'{x(clip(st[0], int((bw - 56) / 8.4)))}</text>')
        for j, line in enumerate(wrap(st[1], int((bw - 28) / 7.4), 4)):
            out.append(f'<text x="{x0 + 16:.1f}" y="{top + 60 + j * 18}" fill="{SOFT}" font-size="13">{x(line)}</text>')
        if len(st) > 2 and st[2]:
            out.append(f'<text x="{x0 + 16:.1f}" y="{top + bh - 14}" fill="{GOLD2}" font-size="12" class="mono">'
                       f'{x(clip(st[2], int((bw - 24) / 7.2)))}</text>')
        out.append("</g>")
        if i < n - 1:
            a, b, y = x0 + bw + 4, x0 + bw + gap - 4, top + bh / 2
            pid = f"p{i}"
            paths.append(f'<path id="{pid}" d="M{a:.1f} {y} L{b:.1f} {y}" class="wire"/>')
            paths.append(f'<path d="M{b - 7:.1f} {y - 5} L{b:.1f} {y} L{b - 7:.1f} {y + 5}" fill="none" stroke="{GOLD}" stroke-width="2"/>')
            dots.append(dot(pid, i * 0.35, 1.1))
    if spec.get("note"):
        out.append(f'<text x="40" y="{top + bh + 40}" fill="{MUTED}" font-size="14">{x(spec["note"])}</text>')
    return frame(h, spec["caption"], spec["title"], spec.get("subtitle", ""), "\n".join(out + paths + dots))


def terminal(spec):
    lines = spec["lines"]
    top = 112 if spec.get("subtitle") else 96
    lh = 27
    th = 44 + lh * len(lines) + 22
    h = top + th + 34
    n = len(lines)
    cycle = max(8.0, n * 0.7 + 3)
    css = f".tl {{ animation: type {cycle:.1f}s ease-out infinite both; }} " \
          f"@keyframes type {{ 0% {{ opacity: 0; }} 3% {{ opacity: 1; }} 94% {{ opacity: 1; }} 100% {{ opacity: 0; }} }} " \
          f"@media (prefers-reduced-motion: reduce) {{ .tl {{ opacity: 1; }} }}"
    out = [f'<rect x="40" y="{top}" width="{W - 80}" height="{th}" rx="12" fill="#050d1d" stroke="{GOLD}" stroke-opacity=".5"/>',
           f'<circle cx="64" cy="{top + 20}" r="6" fill="{RED}"/><circle cx="84" cy="{top + 20}" r="6" fill="{GOLD2}"/>'
           f'<circle cx="104" cy="{top + 20}" r="6" fill="{GREEN}"/>',
           f'<text x="126" y="{top + 25}" fill="#7f8db0" font-size="13" class="mono">{x(spec.get("window", "terminal"))}</text>']
    for i, (cmd, comment) in enumerate(lines):
        y = top + 60 + i * lh
        delay = i * (cycle - 3) / n
        is_out = cmd.startswith("→")
        body = (f'<tspan fill="{GREEN}">{x(cmd)}</tspan>' if is_out else
                f'<tspan fill="{GOLD2}">$ </tspan><tspan fill="#e8e4d8">{x(cmd)}</tspan>')
        if comment:
            body += f'<tspan fill="#6f7d9e">   # {x(comment)}</tspan>'
        out.append(f'<text x="64" y="{y}" font-size="15" class="mono tl" style="animation-delay:{delay:.2f}s" '
                   f'xml:space="preserve">{body}</text>')
    out.append(f'<rect x="64" y="{top + 60 + n * lh - 14}" width="10" height="18" fill="{GOLD2}" class="pulse"/>')
    return frame(h, spec["caption"], spec["title"], spec.get("subtitle", ""), "\n".join(out), css)


def bars(spec):
    data = spec["bars"]
    top = 128 if spec.get("subtitle") else 106
    bh, gap = 38, 16
    h = top + len(data) * (bh + gap) + 50
    mx = max(v for _, v, _ in data)
    lw, scale = 190, (W - 80 - 190 - 330) / mx
    css = "".join(f".b{i} {{ animation: grow{i} 4.5s cubic-bezier(.2,.8,.2,1) infinite; }} "
                  f"@keyframes grow{i} {{ 0% {{ width: 0; }} 30%, 85% {{ width: {v * scale:.0f}px; }} 100% {{ width: 0; }} }}"
                  for i, (_, v, _) in enumerate(data))
    out = []
    for i, (label, v, ex) in enumerate(data):
        y = top + i * (bh + gap)
        out.append(f'<text x="40" y="{y + 25}" fill="{INK}" font-size="16" font-weight="700">{x(label)}</text>')
        out.append(f'<rect x="{40 + lw}" y="{y}" width="{mx * scale:.0f}" height="{bh}" rx="8" fill="{CARD}" stroke="{GOLD}" stroke-opacity=".25"/>')
        out.append(f'<rect x="{40 + lw}" y="{y}" width="{v * scale:.0f}" height="{bh}" rx="8" fill="url(#gold)" class="b{i}" '
                   f'style="animation-delay:{i * 0.15:.2f}s"/>')
        out.append(f'<text x="{40 + lw + mx * scale + 16:.0f}" y="{y + 25}" fill="{GOLD2}" font-size="18" font-weight="800">{v}</text>')
        out.append(f'<text x="{40 + lw + mx * scale + 56:.0f}" y="{y + 25}" fill="{SOFT}" font-size="14">{x(clip(ex, 34))}</text>')
    if spec.get("note"):
        out.append(f'<text x="40" y="{h - 26}" fill="{MUTED}" font-size="14">{x(spec["note"])}</text>')
    return frame(h, spec["caption"], spec["title"], spec.get("subtitle", ""), "\n".join(out), css)


def layers(spec):
    rows = spec["layers"]
    top = 126 if spec.get("subtitle") else 104
    lh, gap = 58, 12
    h = top + len(rows) * (lh + gap) + 40
    out = [f'<path id="drop" d="M{W - 90} {top - 6} L{W - 90} {top + len(rows) * (lh + gap) - gap + 6}" class="wire"/>']
    for i, (name, desc, code) in enumerate(rows):
        y = top + i * (lh + gap)
        inset = i * 18
        out.append(f'<g class="rise" style="animation-delay:{i * 0.1:.2f}s">')
        out.append(f'<rect x="{40 + inset}" y="{y}" width="{W - 180 - 2 * inset}" height="{lh}" rx="10" class="card"/>')
        out.append(f'<rect x="{40 + inset}" y="{y}" width="6" height="{lh}" rx="3" fill="url(#gold)"/>')
        out.append(f'<text x="{62 + inset}" y="{y + 25}" fill="{INK}" font-size="16" font-weight="700">{x(name)}</text>')
        out.append(f'<text x="{62 + inset}" y="{y + 46}" fill="{SOFT}" font-size="13.5">{x(clip(desc, 92))}</text>')
        if code:
            out.append(f'<text x="{W - 160 - inset}" y="{y + 35}" fill="{GOLD2}" font-size="13" text-anchor="end" class="mono">{x(code)}</text>')
        out.append("</g>")
    out.append(dot("drop", 0, 3.2))
    out.append(dot("drop", 1.6, 3.2))
    out.append(f'<text x="{W - 90}" y="{top - 14}" fill="{GOLD2}" font-size="12" text-anchor="middle">every call</text>')
    return frame(h, spec["caption"], spec["title"], spec.get("subtitle", ""), "\n".join(out))


def timeline(spec):
    vs = spec["versions"]
    top = 150 if spec.get("subtitle") else 128
    h = top + 230
    n = len(vs)
    step = (W - 120) / (n - 1)
    cur = next(i for i, v in enumerate(vs) if v[2] == "current")
    y = top + 40
    out = [f'<line x1="60" y1="{y}" x2="{W - 60}" y2="{y}" stroke="{GOLD}" stroke-opacity=".25" stroke-width="4"/>',
           f'<path id="tl" d="M60 {y} L{60 + cur * step:.0f} {y}" stroke="url(#gold)" stroke-width="4" fill="none"/>',
           dot("tl", 0, 3.0)]
    for i, (ver, theme, status) in enumerate(vs):
        cx = 60 + i * step
        col = {"done": GOLD, "current": GOLD2, "next": BLUE}.get(status, MUTED)
        r = 13 if status == "current" else 9
        out.append(f'<circle cx="{cx:.0f}" cy="{y}" r="{r}" fill="{col if status in ("done", "current") else NAVY1}" '
                   f'stroke="{col}" stroke-width="2.5"/>')
        if status == "current":
            out.append(f'<circle cx="{cx:.0f}" cy="{y}" r="22" fill="none" stroke="{GOLD2}" stroke-width="2" class="pulse"/>')
        out.append(f'<text x="{cx:.0f}" y="{y - 26}" fill="{INK}" font-size="15" font-weight="800" text-anchor="middle">{x(ver)}</text>')
        ty = y + 44 + (i % 2) * 64
        out.append(f'<line x1="{cx:.0f}" y1="{y + 14}" x2="{cx:.0f}" y2="{ty - 16}" stroke="{col}" stroke-opacity=".4"/>')
        for j, line in enumerate(wrap(theme, 18, 3)):
            out.append(f'<text x="{cx:.0f}" y="{ty + j * 17}" fill="{SOFT if status != "current" else GOLD2}" '
                       f'font-size="13" text-anchor="middle">{x(line)}</text>')
    legend = [("released", GOLD), ("current", GOLD2), ("next", BLUE), ("planned", MUTED)]
    for i, (k, c) in enumerate(legend):
        out.append(f'<circle cx="{60 + i * 130}" cy="{h - 30}" r="6" fill="{c}"/>'
                   f'<text x="{72 + i * 130}" y="{h - 25}" fill="{MUTED}" font-size="13">{k}</text>')
    return frame(h, spec["caption"], spec["title"], spec.get("subtitle", ""), "\n".join(out))


# ───────────────────────────── application figures (from the programs) ─────────────────────────────
def program_meta(path: Path):
    head = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("//"):
            head.append(line[2:].strip())
        elif line.strip():
            break
    first = head[0] if head else path.stem.replace("_", " ").title()
    title, _, desc = first.partition(" — ")
    return title.strip(), desc.strip()


def find_agent(prog, label):
    name = label.replace(" × each", "")
    if name in prog.agents:
        return prog.agents[name]
    for k, a in prog.agents.items():
        if k.endswith("." + name) or k.split(".")[-1] == name.split(".")[-1]:
            return a
    return None


def reduce_edges(nodes, edges):
    """Drop a data edge a→b when b is reachable from a another way (transitive reduction). The figure keeps
    every dependency, but each one is drawn once, along its most specific path."""
    succ = {}
    for a, b, _ in edges:
        succ.setdefault(a, set()).add(b)

    def reachable(a, b, skip):
        stack, seen = [n for n in succ.get(a, ()) if (a, n) != skip], set()
        while stack:
            n = stack.pop()
            if n == b:
                return True
            if n not in seen:
                seen.add(n)
                stack.extend(succ.get(n, ()))
        return False

    out = []
    for a, b, dashed in edges:
        if not dashed and reachable(a, b, (a, b)):
            continue
        if (a, b, dashed) not in out:
            out.append((a, b, dashed))
    return out


def layout_flow(nodes, edges):
    ids = [n[0] for n in nodes]
    layer = {i: 0 for i in ids}
    for _ in range(len(ids)):
        changed = False
        for a, b, _ in edges:
            if layer[b] < layer[a] + 1:
                layer[b] = layer[a] + 1
                changed = True
        if not changed:
            break
    cols: dict[int, list] = {}
    for i in ids:
        cols.setdefault(layer[i], []).append(i)
    pos = {}
    for L in sorted(cols):
        col = cols[L]
        if L:
            preds = {i: [pos[a] for a, b, _ in edges if b == i and a in pos] for i in col}
            col.sort(key=lambda i: (sum(preds[i]) / len(preds[i])) if preds[i] else 1e9)
        for r, i in enumerate(col):
            pos[i] = r - (len(col) - 1) / 2
    return layer, pos, cols


def app_figure(app: str, prog_path: Path):
    import algolang as al
    import algoc
    title, desc = program_meta(prog_path)
    prog = al.load(str(prog_path))._prog
    nodes, edges = algoc.flow_graph(prog)
    edges = reduce_edges(nodes, edges)
    kinds = {n[0]: n for n in nodes}
    layer, pos, cols = layout_flow(nodes, edges)
    L = max(layer.values()) + 1
    maxrows = max(len(c) for c in cols.values())
    top = 140
    rowh = 84
    area = max(maxrows * rowh, 200)
    h = top + area + 112
    cw = (W - 80) / L
    bw = max(104, min(196, cw - 34))
    cx = {i: 40 + (layer[i] + 0.5) * cw for i in kinds}
    cy = {i: top + area / 2 + pos[i] * rowh for i in kinds}

    def port(i, side):
        k = kinds[i][2]
        half = {"cond": 24, "emit": 17, "input": bw / 2}.get(k, bw / 2)
        return cx[i] + (half if side == "out" else -half), cy[i]

    paths, dots, shapes = [], [], []
    data_i = 0
    for e, (a, b, dashed) in enumerate(edges):
        (x1, y1), (x2, y2) = port(a, "out"), port(b, "in")
        if x2 <= x1:
            x2 = x1 + 10
        mid = (x1 + x2) / 2
        pid = f"e{e}"
        paths.append(f'<path id="{pid}" d="M{x1:.1f} {y1:.1f} C {mid:.1f} {y1:.1f}, {mid:.1f} {y2:.1f}, {x2:.1f} {y2:.1f}" '
                     f'class="{"ctl" if dashed else "wire"}"/>')
        if not dashed and data_i < 14:
            dots.append(dot(pid, (data_i * 0.37) % 2.2, 1.7))
            data_i += 1

    n_agents = n_dec = 0
    tools, human, unc = set(), 0, 0
    lab_chars = int((bw - 22) / 8.3)
    for i, (nid, label, kind, sub) in enumerate(nodes):
        X, Y = cx[nid], cy[nid]
        d = f'style="animation-delay:{0.05 * i:.2f}s"'
        if kind == "input":
            shapes.append(f'<g class="rise" {d}><rect x="{X - bw / 2:.1f}" y="{Y - 21:.1f}" width="{bw:.1f}" height="42" rx="21" '
                          f'fill="{NAVY0}" stroke="{GOLD2}" stroke-width="1.6"/>'
                          f'<text x="{X:.1f}" y="{Y - 2:.1f}" fill="{INK}" font-size="14.5" font-weight="700" text-anchor="middle">{x(clip(label, lab_chars))}</text>'
                          f'<text x="{X:.1f}" y="{Y + 13:.1f}" fill="{SOFT}" font-size="11" text-anchor="middle">input</text></g>')
        elif kind == "cond":
            n_dec += 1
            ctext = clip(label[3:] if label.startswith("if ") else label, int(cw / 6.4))
            shapes.append(f'<g class="rise" {d}><polygon points="{X},{Y - 24} {X + 24},{Y} {X},{Y + 24} {X - 24},{Y}" '
                          f'fill="{CARD}" stroke="{GOLD2}" stroke-width="1.8"/>'
                          f'<text x="{X:.1f}" y="{Y + 4:.1f}" fill="{GOLD2}" font-size="12" font-weight="800" text-anchor="middle">if</text>'
                          f'<rect x="{X - len(ctext) * 3.6 - 6:.1f}" y="{Y - 46:.1f}" width="{len(ctext) * 7.2 + 12:.1f}" height="19" rx="5" '
                          f'fill="{NAVY0}" fill-opacity=".92" stroke="{GOLD}" stroke-opacity=".35"/>'
                          f'<text x="{X:.1f}" y="{Y - 32:.1f}" fill="{SOFT}" font-size="11.5" text-anchor="middle" class="mono">{x(ctext)}</text></g>')
        elif kind == "emit":
            shapes.append(f'<g {d}><circle cx="{X:.1f}" cy="{Y:.1f}" r="17" fill="url(#gold)" class="pulse"/>'
                          f'<text x="{X:.1f}" y="{Y + 4:.1f}" fill="{NAVY1}" font-size="10.5" font-weight="800" text-anchor="middle">emit</text></g>')
        else:
            n_agents += 1
            ag = find_agent(prog, label)
            uses = list(ag.uses) if ag else []
            tools.update(uses)
            pol = ag.policy if ag else {}
            is_h = bool(pol.get("human_below") or pol.get("require_human") or pol.get("human_always")
                        or pol.get("approvals"))
            is_u = bool(ag and str(ag.returns).startswith("uncertain"))
            human += is_h
            unc += is_u
            short = label.split(".")[-1]
            line2 = (f"uses {uses[0]}" + (f" +{len(uses) - 1}" if len(uses) > 1 else "")) if uses else \
                    (sub.replace("→ ", "→ ") if sub and sub != "→ emit" else (ag.role if ag and ag.role else ""))
            stroke = GOLD if kind != "branch" else GOLD2
            dash = ' stroke-dasharray="5 3"' if kind == "branch" else ""
            shapes.append(f'<g class="rise" {d}><rect x="{X - bw / 2:.1f}" y="{Y - 25:.1f}" width="{bw:.1f}" height="50" rx="10" '
                          f'fill="{CARD}" stroke="{stroke}" stroke-width="1.6"{dash}/>'
                          f'<text x="{X:.1f}" y="{Y - 4:.1f}" fill="{INK}" font-size="14.5" font-weight="700" text-anchor="middle">{x(clip(short, lab_chars))}</text>'
                          f'<text x="{X:.1f}" y="{Y + 13:.1f}" fill="{SOFT}" font-size="11" text-anchor="middle">{x(clip(line2, int((bw - 12) / 6.2)))}</text>')
            bx = X + bw / 2
            if kind == "par":
                shapes.append(f'<text x="{X - bw / 2 + 8:.1f}" y="{Y - 30:.1f}" fill="{GOLD2}" font-size="11" font-weight="800">PAR</text>')
            if is_u:
                n = pol.get("samples", "")
                shapes.append(f'<rect x="{bx - 54:.1f}" y="{Y - 36:.1f}" width="50" height="17" rx="8.5" fill="{BLUE}"/>'
                              f'<text x="{bx - 29:.1f}" y="{Y - 24:.1f}" fill="{NAVY1}" font-size="10" font-weight="800" text-anchor="middle">~ ×{n or "N"}</text>')
            if is_h:
                shapes.append(f'<g class="pulse"><rect x="{bx - (112 if is_u else 58):.1f}" y="{Y - 36:.1f}" width="54" height="17" rx="8.5" fill="{GOLD}"/>'
                              f'<text x="{bx - (85 if is_u else 31):.1f}" y="{Y - 24:.1f}" fill="{NAVY1}" font-size="10" font-weight="800" text-anchor="middle">⚑ human</text></g>')
            shapes.append("</g>")

    plural = (lambda n, w: f"{n} {w}{'' if n == 1 else 's'}")
    level = prog.risk[0] if getattr(prog, "risk", None) else None
    chips = ([f"{level} risk"] if level else []) + \
        [plural(n_agents, "agent call"), plural(len(tools), "tool"), plural(n_dec, "decision")]
    pols = [a.policy for a in prog.agents.values()]
    if unc:
        chips.append(f"{unc} uncertain")
    if human:
        chips.append(f"{human} human gate{'s' if human > 1 else ''}")
    for s in prog.streams:
        chips.append(f"stream · pulse/{s.bus}")
    if getattr(prog, "circuits", None):
        chips.append(f"{len(prog.circuits)} circuit{'s' if len(prog.circuits) > 1 else ''}")
    if any(pl.get("approvals", 0) >= 2 for pl in pols):
        chips.append("four-eyes")
    if pols and all(pl.get("redact_pii") for pl in pols):
        chips.append("PII masked")
    if any(pl.get("explain") == "evidence" for pl in pols):
        chips.append("explained")
    risk_color = {"high": "#e0705c", "limited": "#e9c75a", "minimal": "#6cc28a"}
    right, cx0 = [], 40
    for c in chips:
        w = 16 + len(c) * 7.3
        col = risk_color.get(c.split(" ")[0], GOLD) if c.endswith(" risk") else GOLD
        txt = col if c.endswith(" risk") else "#f1dc94"
        right.append(f'<rect x="{cx0:.0f}" y="{top - 30}" width="{w:.0f}" height="24" rx="12" fill="{col}" fill-opacity=".13" '
                     f'stroke="{col}" stroke-opacity=".75"/><text x="{cx0 + w / 2:.0f}" y="{top - 13}" fill="{txt}" '
                     f'font-size="12.5" font-weight="{700 if c.endswith(" risk") else 400}" text-anchor="middle">{x(c)}</text>')
        cx0 += w + 10
    ly = h - 62
    leg = [("agent", f'<rect x="0" y="-9" width="26" height="18" rx="5" fill="{CARD}" stroke="{GOLD}"/>'),
           ("branch agent", f'<rect x="0" y="-9" width="26" height="18" rx="5" fill="{CARD}" stroke="{GOLD2}" stroke-dasharray="4 2"/>'),
           ("decision", f'<polygon points="13,-10 24,0 13,10 2,0" fill="{CARD}" stroke="{GOLD2}"/>'),
           ("uncertain (sampled)", f'<rect x="0" y="-8" width="26" height="16" rx="8" fill="{BLUE}"/>'),
           ("human gate", f'<rect x="0" y="-8" width="26" height="16" rx="8" fill="{GOLD}"/>'),
           ("data", f'<path d="M0 0 L26 0" class="wire"/>'),
           ("control", f'<path d="M0 0 L26 0" class="ctl"/>')]
    lx = 40
    legend = []
    for name, g in leg:
        legend.append(f'<g transform="translate({lx},{ly})">{g}<text x="34" y="5" fill="{MUTED}" font-size="12.5">{x(name)}</text></g>')
        lx += 48 + len(name) * 7.2
    rel = prog_path.relative_to(ROOT).as_posix()
    legend.append(f'<text x="40" y="{h - 38}" fill="{MUTED}" fill-opacity=".85" font-size="12">Drawn automatically from '
                  f'{x(rel)} by tools/make_figures.py — the figure always matches the code.</text>')
    body = "\n".join(right + paths + shapes + dots + legend)
    return frame(h, app.replace("-", " "), title, desc, body)


# ───────────────────────────── section specs ─────────────────────────────
SECTIONS = {
    "01-objective": (cards, dict(
        caption="1 · Objective", title="Ten objectives, one aim: trustworthy agent systems",
        subtitle="Every objective is enforced by the compiler or the runtime, not left to good intentions.", cols=5, lines=3,
        items=[dict(t="Agent-native", d="No functions: every task is an agent with role, goal, tools, model and policy."),
               dict(t="Readable flows", d="Call agents, run them in parallel, branch, emit. Nothing else."),
               dict(t="Safe before run", d="31 compile-time checks stop unsafe programs before any call."),
               dict(t="Governance", d="Budgets, retries, forbidden attributes and human review in the code."),
               dict(t="Accountability", d="Confidence, provenance and an Ed25519-signed, hash-chained audit log."),
               dict(t="Honest uncertainty", d="uncertain<T> agents are sampled; decisions must check confidence."),
               dict(t="Cost and energy", d="Every call priced in $, ₹, watt-hours and CO₂ before it runs."),
               dict(t="Reuse at scale", d="120 domain packs, modules, MCP, AlgoPulse streams, quantum tools."),
               dict(t="For everyone", d="CLI, Studio, Prompt UI, Python SDK and editor support."),
               dict(t="Trustworthy by evidence", d="Risk levels, fairness and robustness tests, system cards, trust reports.")])),
    "02-principles": (layers, dict(
        caption="2 · Design principles", title="Six principles that shape every program",
        subtitle="From the outside in: what is allowed, who decides, and how it is proved.",
        layers=[("Explicit, never ambient", "An agent has only the tools it declares. Nothing is available by default.", "uses kb.search"),
                ("The stricter rule wins", "Organisation policy and program policy are merged; the stricter value applies.", "algo.config.json"),
                ("Hard rules are deterministic", "Limits that must never break are checked in code, not by a model.", 'contains "BREACH"'),
                ("Scores carry their confidence", "Every branch has a visible, recordable reason.", "x.confidence >= 0.7"),
                ("People stay in the loop", "Low-confidence calls go to a human review queue instead of going out.", "require human"),
                ("One engine, many doors", "CLI, Studio, Prompt UI, SDK and language server run the same compiler.", "algo · studio · ui")])),
    "03-whats-new": (cards, dict(
        caption="3 · What's new in v1.0", title="AlgoLang 1.0: a platform teams can build on, share and deploy",
        subtitle="Every release planned since v0.1 has shipped; 1.0 adds the native runtime and the ecosystem around it.",
        cols=4, lines=3, card_h=128,
        items=[dict(t="Typed messages", d="type Claim { … }: fields checked by the compiler and every answer validated.", tag="E131 · E132"),
               dict(t="AlgoIR & AlgoVM", d="Signed, portable programs run on AlgoLang's own VM; no generated code.", tag="build --ir"),
               dict(t="Packages & registry", d="Signed .algopkg archives, semver, algo.lock, use \"pkg:…\".", tag="algo pkg"),
               dict(t="Studio SSO & roles", d="OpenID Connect sign-in; viewer, reviewer, author and admin roles.", tag="OIDC · RBAC")])),
    "04-get-started": (terminal, dict(
        caption="4 · Get started", title="From install to a governed multi-agent run in minutes",
        subtitle="Offline by default: no API key needed until you add --live.", window="algo — enterprise quick start",
        lines=[("pip install git+https://github.com/drssnaiml1-cell/algolang", "once"),
               ("algo init acme && cd acme", "config, tools, knowledge base, sample program"),
               ('algo domains "triage insurance claims"', "search 120 domain packs"),
               ('algo run pack:insurance.claims_triage --arg "claim=Rear-end collision"', ""),
               ("→ ok · 4 agents · confidence 0.86 · audit chain intact", ""),
               ("algo batch programs/claims_ops.algo --input data/claims.csv --workers 16", ""),
               ("algo review", "human review queue"),
               ("algo audit verify", "every hash chain checked"),
               ("algo studio", "graphical mode  ·  algo ui = prompt mode")])),
    "05-50-programs": (bars, dict(
        caption="5 · Learn by example", title="50 sample programs across 20 sectors, by pattern",
        subtitle="Every program in the PDF is runnable in examples/50-programs/ and runs in CI on every push.",
        bars=[("pipeline", 15, "P15 KYC Onboarding"), ("router", 13, "P17 Claims Triage"), ("fan-out", 9, "P12 Drug Interaction Check"),
              ("par for", 5, "P24 Literature Review"), ("single", 4, "P01 Hello Greeter"), ("committee", 4, "P14 Credit Committee")],
        note="AlgoLang: 50 Sample Programs (PDF, 106 pages): input, code and output in CLI, Studio and Prompt UI.")),
    "06-enterprise-apps": (cards, dict(
        caption="6 · Enterprise applications", title="Twenty-two governed applications, ready to run",
        subtitle="Each has its own org policy, company tools, knowledge base, programs, batch data, behaviour tests and system cards.",
        cols=5, lines=2, card_h=96,
        items=[dict(t="Claims Operations", d="Insurance · FNOL to payout or SIU"),
               dict(t="Hospital Care", d="Healthcare · ER triage, discharge"),
               dict(t="Bank Credit & KYC", d="Banking · committee, sanctions"),
               dict(t="Admissions & OBE", d="Education · fair panel, CO-PO"),
               dict(t="SOC Command", d="Cybersecurity · alerts, PQC, streams"),
               dict(t="Supply Chain Tower", d="Logistics · exceptions, routes"),
               dict(t="Citizen Services", d="Government · grievances, welfare"),
               dict(t="Legal Contract Desk", d="Legal · NDA triage, clause review"),
               dict(t="Algo Trading Desk", d="Markets · risk gate, VaR, streams"),
               dict(t="Quantum Lab", d="Quantum · QAOA verified, circuits"),
               dict(t="LLM & SLM Optimizer", d="AI platform · cascades, graph optimisation"),
               dict(t="ML Model Factory", d="ML & DL · train, compare, drift"),
               dict(t="RL Control Room", d="RL · shielded microgrid dispatch"),
               dict(t="Responsible XAI", d="Shapley, fairness audit, recourse"),
               dict(t="NLP Documents", d="NLP · triage, entities, summaries"),
               dict(t="Bhasha Desk", d="Indian languages · 8 scripts"),
               dict(t="Digital Health", d="NEWS2 · 5,000 patients · stream"),
               dict(t="Network Biology Lab", d="Targets, enrichment, sequences"),
               dict(t="Pump Maintenance", d="Engineering · 1,000 pumps"),
               dict(t="City Operations", d="Smart city · AQI, waste, power"),
               dict(t="Transport Network", d="Detours, signals, demand, buses"),
               dict(t="Quantum AI Lab", d="VQE, kernels, budgets, hardware")])),
    "09-language": (pipeline, dict(
        caption="9 · The language", title="From .algo source to a governed run",
        subtitle="One small grammar; the compiler proves the rules before the runtime executes them.",
        steps=[("Source", "model, tool, agent, flow, stream, circuit and eval declarations", ".algo"),
               ("Parse", "Lark grammar to an abstract syntax tree, with file and line for every node", "grammar.lark"),
               ("Check", "31 rules: agents only, declared tools, forbidden attributes, risk-level safeguards", "E100–E130"),
               ("Generate", "Plain Python that calls the runtime; readable and testable", "algoc.py"),
               ("Run", "Policies, budgets, sampling, human gate and audit for every agent call", "algoruntime.py")])),
    "10-governance": (layers, dict(
        caption="10 · Governance", title="Defence in depth for every agent call",
        subtitle="Each layer can stop a call; every outcome, allowed or blocked, is written to the signed audit chain.",
        layers=[("Organisation policy", "forbidden attributes, allowed tools, caps, review threshold, pinned MCP servers", "algo.config.json"),
                ("Compile-time checks", "unsafe programs never start; high-risk programs must carry every safeguard", "E100–E130"),
                ("Privacy and fencing", "personal data masked, protected values withheld, untrusted tool output fenced", "redact pii"),
                ("Budgets and sampling", "tokens, $, ₹ and Wh priced before the call; uncertain agents sampled", "samples 5"),
                ("Explanation and people", "grounded reasons with evidence; review queue with four-eyes approval", "require approvals 2"),
                ("Signed audit", "Ed25519 signatures over a SHA-256 chain; retention keeps it verifiable", "algo audit verify")])),
    "11-sdk": (pipeline, dict(
        caption="11 · Python SDK", title="The same engine from Python",
        subtitle="import algolang — every mode (CLI, Studio, Prompt UI) is built on this API.",
        steps=[("Configure", "Org policy in code: forbidden attributes, review threshold", "al.configure(…)"),
               ("Find", "Search 120 domain packs by plain-English need", "al.domains.search"),
               ("Run", "Values, confidence, provenance, stats, audit path", "prog.run(…)"),
               ("Scale", "Thousands of records under one concurrency limit", "run_batch(workers=16)"),
               ("Oversee", "Approve or reject queued items, verify audit chains", "al.review · al.audit")])),
    "12-developers": (cards, dict(
        caption="12 · For developers", title="Three tracks, one test suite",
        subtitle="DEVELOPER_GUIDE.md walks each track; make check runs ruff, pytest and a lint of every .algo file.",
        cols=3, lines=3, card_h=128,
        items=[dict(t="Application developers", d="SDK, company tools as Python functions, *.algotest.json behaviour tests, algo dev ci.", tag="algo dev ci"),
               dict(t="Language contributors", d="Architecture, recipes for new syntax, error codes, tools and packs, the test suite.", tag="make check"),
               dict(t="Maintainers", d="CI on Linux, macOS and Windows, releases from a button, the website and the container.", tag="Actions → Release")])),
    "13-roadmap": (timeline, dict(
        caption="13 · Roadmap", title="Where AlgoLang has been, and where it is going",
        subtitle="Every planned release has shipped, one at a time, each with tests, CI, documentation and figures.",
        versions=[("v0.1", "agents, flows, policies", "done"), ("v0.2", "enterprise, 120 packs, SDK", "done"),
                  ("v0.3", "uncertainty, evals, MCP, LSP", "done"), ("v0.3.2–3", "quantum tools and circuits", "done"),
                  ("v0.3.4", "AlgoPulse™, live figures", "done"), ("v0.4", "Trustworthy AI, LLM & SLM graphs", "done"),
                  ("v0.5", "ten large-scale domain apps", "done"), ("v0.6", "Quantum AI on hardware", "done"),
                  ("v0.7", "Interoperability", "done"),
                  ("v1.0", "native runtime, ecosystem", "current")])),
    "14-layout": (cards, dict(
        caption="14 · Repository layout", title="What lives where",
        subtitle="Compiler and runtime at the root; libraries, applications and documentation in their own folders.",
        cols=3, lines=3, card_h=122,
        items=[dict(t="Compiler & runtime", d="grammar.lark, algoc.py, algoruntime.py, algoeval.py, algolsp.py", tag="core"),
               dict(t="Trust layer", d="algotrust.py (privacy, fencing, signing), algoassure.py (cards, reports, evidence)", tag="v0.4"),
               dict(t="Engines", d="algoir.py (AlgoVM), algopkg.py, algoauth.py, algoserve.py, algoqpu.py, algopulse.py", tag="engines"),
               dict(t="Modes", d="algoshell, algostudio, algoprompt.html, algoagent, the algo command", tag="doors"),
               dict(t="Libraries & docs", d="packs/ (120 domain packs), examples/, docs/, guides, tests/, tools/, CI", tag="reuse"),
               dict(t="Applications", d="enterprise-apps/: 22 governed apps with tools, data, tests and system cards", tag="apps")])),
    "15-author": (cards, dict(
        caption="15 · Author and licence", title="Designed in Hyderabad by AlgoProfessor AI R&D Solutions",
        cols=3, lines=3, card_h=118,
        items=[dict(t="Dr. S. Satyanarayana", d="Ph.D., PDF (AI) · Founder, CEO & Chief Agentic AI Scientist", n="✦"),
               dict(t="AlgoProfessor AI R&D", d="www.algoprofessor.com · ceo@algoprofessor.com", n="✦"),
               dict(t="Apache License 2.0", d="Open source. Contributions welcome: CONTRIBUTING.md and the Code of Conduct.", n="✦")])),
}


def realtime_figure():
    """§7: AlgoPulse™, drawn by hand-tuned coordinates."""
    css = (".lane {{ animation: slide 3s linear infinite; }} .lane2 {{ animation-duration: 2.4s; }} .lane3 {{ animation-duration: 3.6s; }} "
           "@keyframes slide {{ from {{ transform: translateX(-56px); }} to {{ transform: none; }} }}").replace("{{", "{").replace("}}", "}")
    h = 470
    p = []
    p.append('<defs><path id="i1" d="M228 178 C 280 178, 280 214, 316 214"/><path id="i2" d="M228 260 L 316 260"/>'
             '<path id="i3" d="M228 342 C 280 342, 280 306, 316 306"/><path id="m" d="M596 260 L 660 260"/>'
             '<path id="o1" d="M912 260 C 950 260, 950 170, 980 170"/><path id="o2" d="M912 260 L 980 260"/>'
             '<path id="o3" d="M912 260 C 950 260, 950 350, 980 350"/></defs>')
    p.append('<use href="#i1" class="wire"/><use href="#i2" class="wire"/><use href="#i3" class="wire"/><use href="#m" class="wire"/>'
             f'<use href="#o1" class="wire" style="stroke:{GREEN}"/><use href="#o2" class="wire"/><use href="#o3" class="wire" style="stroke:{RED}"/>')
    for i, (t, s) in enumerate([("Order system", "order intents"), ("SIEM / EDR", "security alerts"), ("Apps & sensors", "claims · tickets · IoT")]):
        y = 152 + i * 82
        p.append(f'<rect x="40" y="{y}" width="188" height="52" rx="9" class="card"/><text x="58" y="{y + 23}" fill="{INK}" font-size="15" '
                 f'font-weight="700">{x(t)}</text><text x="58" y="{y + 41}" fill="{SOFT}" font-size="12">{x(s)}</text>')
    p.append(f'<text x="40" y="136" fill="{GOLD}" font-size="12" letter-spacing="2.4" font-weight="700">PRODUCERS</text>')
    p.append(f'<rect x="316" y="132" width="280" height="250" rx="12" fill="{CARD}" stroke="{GOLD2}" stroke-width="2"/>'
             f'<text x="336" y="160" fill="{GOLD2}" font-size="17" font-weight="800">AlgoPulse™ bus</text>'
             f'<text x="336" y="180" fill="{SOFT}" font-size="12">append-only · durable · numbered offsets</text>')
    for j, cls in enumerate(["lane", "lane lane2", "lane lane3"]):
        y = 196 + j * 46
        p.append(f'<rect x="336" y="{y}" width="240" height="30" rx="5" fill="{NAVY0}"/>')
        cells = "".join(f'<rect x="{348 + k * 56}" y="{y + 6}" width="44" height="18" rx="3" fill="{GOLD2}" fill-opacity="{0.95 - k * 0.18:.2f}"/>'
                        for k in range(5))
        p.append(f'<g><svg x="336" y="{y}" width="240" height="30" viewBox="336 {y} 240 30" overflow="hidden">'
                 f'<g class="{cls}">{cells}</g></svg></g>')
    p.append(f'<text x="336" y="348" fill="{SOFT}" font-size="12">orders.intent · soc.alerts · …</text>'
             f'<text x="336" y="368" fill="{SOFT}" font-size="12">local folder, or algo pulse serve (token)</text>')
    p.append(f'<rect x="660" y="132" width="252" height="250" rx="12" fill="{CARD}" stroke="{GOLD}" stroke-width="1.6"/>'
             f'<text x="680" y="160" fill="{INK}" font-size="17" font-weight="800">stream block</text>'
             f'<text x="680" y="180" fill="{SOFT}" font-size="12">consumer group · max in flight 8</text>'
             f'<text x="680" y="210" fill="#e8e4d8" font-size="12.5" class="mono">map order = event.order</text>'
             f'<text x="680" y="230" fill="#e8e4d8" font-size="12.5" class="mono">key event.order_id</text>'
             f'<rect x="680" y="246" width="212" height="56" rx="8" fill="{NAVY0}" stroke="{GOLD}" stroke-opacity=".4"/>'
             f'<text x="692" y="268" fill="{INK}" font-size="13.5" font-weight="700">flow main → agents</text>'
             f'<text x="692" y="288" fill="{SOFT}" font-size="12">policies · budgets · human gate</text>'
             f'<text x="680" y="328" fill="{SOFT}" font-size="12">audit chain + trace per event</text>'
             f'<text x="680" y="348" fill="{SOFT}" font-size="12">dedupe by key · at-least-once</text>'
             f'<text x="680" y="368" fill="{SOFT}" font-size="12">offset committed after results</text>')
    for k, (t, s, c, tc) in enumerate([("orders.decisions", "ok · completed decisions", GREEN, "#bff0cd"),
                                       ("orders.review", "escalated · a person decides", GOLD2, "#ffe7a3"),
                                       ("orders.dlq", "invalid · blocked · failed", RED, "#ffc2b6")]):
        y = 142 + k * 90
        p.append(f'<rect x="980" y="{y}" width="260" height="56" rx="10" fill="{CARD}" stroke="{c}" stroke-width="1.6"/>'
                 f'<text x="998" y="{y + 24}" fill="{tc}" font-size="15" font-weight="700">{x(t)}</text>'
                 f'<text x="998" y="{y + 43}" fill="{SOFT}" font-size="12">{x(s)}</text>')
    for d_, (pid, dl, col) in enumerate([("i1", 0, None), ("i2", .5, None), ("i3", .9, None), ("m", .2, None),
                                         ("o1", 0, "#9be7b0"), ("o2", .45, None), ("o3", .9, "#ff9a86")]):
        p.append(dot(pid, dl, 1.3, col))
    p.append(f'<text x="40" y="{h - 44}" fill="{MUTED}" font-size="13">Nothing to install beyond AlgoLang. The compiler checks every stream (E122): '
             f'the flow and its inputs exist, mappings read from the event,</text>'
             f'<text x="40" y="{h - 26}" fill="{MUTED}" font-size="13">and no result topic is the source topic. Every event ends in exactly one result topic.</text>')
    return frame(h, "7 · Real-time events", "AlgoPulse™: AlgoLang's built-in event engine",
                 "algo stream program.algo --pulse   ·   algo pulse serve   ·   algo pulse topics", "\n".join(p), css)


def main():
    (OUT / "sections").mkdir(parents=True, exist_ok=True)
    (OUT / "apps").mkdir(parents=True, exist_ok=True)
    written = []
    for name, (fn, spec) in SECTIONS.items():
        f = OUT / "sections" / f"{name}.svg"
        f.write_text(fn(spec), encoding="utf-8")
        written.append(f)
    f = OUT / "sections" / "07-realtime.svg"
    f.write_text(realtime_figure(), encoding="utf-8")
    written.append(f)
    for app in sorted((ROOT / "enterprise-apps").iterdir()):
        progs = sorted((app / "programs").glob("*.algo")) if (app / "programs").exists() else []
        for prog in progs:
            f = OUT / "apps" / f"{app.name}--{prog.stem}.svg"
            f.write_text(app_figure(app.name, prog), encoding="utf-8")
            written.append(f)
    for f in written:
        print(f"  {f.relative_to(ROOT)}")
    print(f"{len(written)} figures written")


if __name__ == "__main__":
    main()
