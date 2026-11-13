"""Draw the README header assets (docs/images/header/): wordmark, works-with strip, two highlight cards, a terminal
panel of real toolchain output, and a release-growth chart computed from the git tags.

    python tools/make_header.py
"""
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images" / "header"
NAVY, NAVY2, GOLD, GOLD2, INK, MUTED = "#0B1F3A", "#16305A", "#C9A227", "#F2D372", "#1F2937", "#6B7280"
SANS = "'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "'JetBrains Mono','DejaVu Sans Mono',Consolas,monospace"


def logo(x, y, s=1.0):
    """The AlgoLang mark: a gold hub with eight agent nodes (radial, like a sun)."""
    parts = [f'<g transform="translate({x},{y}) scale({s})">']
    import math
    for k in range(8):
        a = k * math.pi / 4
        x1, y1 = 15 * math.cos(a), 15 * math.sin(a)
        x2, y2 = 34 * math.cos(a), 34 * math.sin(a)
        parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{GOLD}" stroke-width="5" stroke-linecap="round"/>')
        parts.append(f'<circle cx="{x2:.1f}" cy="{y2:.1f}" r="6.5" fill="{GOLD if k % 2 else GOLD2}"/>')
    parts.append(f'<circle r="13" fill="{NAVY}"/><circle r="6" fill="{GOLD}"/></g>')
    return "".join(parts)


DARK = ("<style>@media (prefers-color-scheme: dark){.ink{fill:#E8ECF4}.sub{fill:#9FB0C8}}</style>")


def wordmark():
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="560" height="120" viewBox="0 0 560 120" role="img" '
            f'aria-label="AlgoLang">{DARK}{logo(64, 60, 1.25)}'
            f'<text class="ink" x="132" y="80" font-family="{MONO}" font-size="62" font-weight="600" fill="{NAVY}">algo'
            f'<tspan fill="{GOLD}">lang</tspan></text></svg>')


def works_with():
    items = ["Claude", "Model Context Protocol", "Qiskit · OpenQASM", "Jupyter · Colab", "Ed25519 · ML-DSA"]
    widths = [len(it) * 9.1 for it in items]
    w = int(140 + sum(widths) + 44 * len(items))
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="64" viewBox="0 0 {w} 64" role="img" '
           f'aria-label="Works with {", ".join(items)}">{DARK}',
           f'<text class="ink" x="4" y="26" font-family="{MONO}" font-size="12" font-weight="700" fill="{INK}" letter-spacing="1.5">'
           f'WORKS WITH</text><text class="sub" x="4" y="44" font-family="{MONO}" font-size="12" fill="{MUTED}" letter-spacing="1">'
           f'// v1.0 · 2026</text>']
    x = 140
    for it in items:
        out.append(f'<rect x="{x}" y="14" width="9" height="9" rx="2" fill="{GOLD}" transform="rotate(45 {x + 4.5} 18.5)"/>'
                   f'<text class="ink" x="{x + 18}" y="25" font-family="{SANS}" font-size="17" font-weight="700" fill="{NAVY}">'
                   f'{escape(it)}</text>')
        x += 18 + len(it) * 9.1 + 26
    out.append("</svg>")
    return "".join(out)


def card(label, title, icon):
    icons = {"star": '<path d="M0,-15 L4.4,-4.6 L15,-4.6 L6.5,2 L9.6,13 L0,6.6 L-9.6,13 L-6.5,2 L-15,-4.6 L-4.4,-4.6 Z" fill="{c}"/>',
             "check": '<path d="M-10,0 L-3,8 L11,-9" fill="none" stroke="{c}" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>'}
    ic = icons[icon].format(c=GOLD if icon == "star" else "#1F8A5B")
    ring = "#E9DFB8" if icon == "star" else "#CBE8D8"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="340" height="88" viewBox="0 0 340 88" role="img" '
            f'aria-label="{escape(label)}: {escape(title)}">'
            f'<rect x="1" y="1" width="338" height="86" rx="12" fill="#FFFDF6" stroke="{ring}" stroke-width="2"/>'
            f'<circle cx="46" cy="44" r="25" fill="none" stroke="{ring}" stroke-width="3"/>'
            f'<g transform="translate(46,44)">{ic}</g>'
            f'<text x="86" y="35" font-family="{SANS}" font-size="11" font-weight="700" fill="{MUTED}" letter-spacing="1.6">'
            f'{escape(label.upper())}</text>'
            f'<text x="86" y="62" font-family="{SANS}" font-size="20" font-weight="700" fill="{NAVY}">{escape(title)}</text></svg>')


TERMINAL = [
    ("$", "algo check programs/loan_decision.algo"),
    ("ok", "✓ loan_decision.algo: 8 agents, 1 flow(s), 3 tool(s) — no errors"),
    ("$", "algo eval programs/loan_decision.algo"),
    ("ok", "✓ salaried applicant"),
    ("dim", "    fair across gender (woman, man, non-binary): same decision, score gap 0.000"),
    ("dim", "    fair across marital_status (married, single, divorced): same decision"),
    ("dim", "    robust to typos, paraphrase, reorder: consistency 1.00 over 6 variants"),
    ("ok", "✓ self-employed applicant"),
    ("dim", "    fair across religion (Muslim, Hindu, Christian, Sikh): same decision"),
    ("gold", "  2/2 cases pass"),
    ("$", "algo build programs/loan_decision.algo --ir"),
    ("ok", "✓ built loan_decision.algo → loan_decision.algoir.json  (AlgoIR v1)"),
    ("$", "algo run loan_decision.algoir.json --arg \"application=APP-3101 …\""),
    ("warn", "  → uw.CreditCommittee  ⚠ ESCALATED to human (confidence 0.70 is below 0.9)"),
    ("gold", "■ 8 agent calls · 4 escalated · 0 blocked · audit → runs/loan_decision.audit.jsonl"),
]


def terminal():
    w, h = 640, 375
    col = {"$": "#E8ECF4", "ok": "#7BD88F", "dim": "#9FB0C8", "gold": GOLD2, "warn": "#FFB86B"}
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
           f'aria-label="AlgoLang toolchain: check, fairness and robustness evals, AlgoIR build, a run with a four-eyes review">',
           f'<rect width="{w}" height="{h}" rx="10" fill="#0A1426"/><rect width="{w}" height="30" rx="10" fill="{NAVY2}"/>',
           f'<rect y="20" width="{w}" height="10" fill="{NAVY2}"/>',
           *[f'<circle cx="{18 + 18 * i}" cy="15" r="5.5" fill="{c}"/>' for i, c in enumerate(["#FF5F56", "#FFBD2E", "#27C93F"])],
           f'<text x="{w / 2}" y="20" text-anchor="middle" font-family="{SANS}" font-size="12" fill="#9FB0C8">'
           f'bank-credit-onboarding — algo</text>']
    y = 56
    for kind, text in TERMINAL:
        if kind == "$":
            out.append(f'<text x="16" y="{y}" font-family="{MONO}" font-size="12.5" xml:space="preserve"><tspan fill="{GOLD}">$ </tspan>'
                       f'<tspan fill="{col["$"]}">{escape(text)}</tspan></text>')
        else:
            out.append(f'<text x="16" y="{y}" font-family="{MONO}" font-size="12" fill="{col[kind]}" xml:space="preserve">'
                       f'{escape(text)}</text>')
        y += 22 if kind == "$" else 21
    out.append("</svg>")
    return "".join(out)


def growth():
    tags = subprocess.run(["git", "tag", "--sort=creatordate"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    tags = [t for t in tags if t.startswith("v")]
    rows = []
    for t in tags:
        names = subprocess.run(["git", "ls-tree", "-r", "--name-only", t], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
        apps = len({n.split("/")[1] for n in names if n.startswith("enterprise-apps/") and n.count("/") >= 2
                    and "/programs/" in n})
        tests = sum(1 for n in names if n.startswith("tests/test_") and n.endswith(".py"))
        rows.append((t, apps, tests))
    w, h, left, bottom, top = 640, 375, 56, 64, 60
    pw, ph = w - left - 24, h - top - bottom
    ymax = max(max(r[1] for r in rows), 24)
    step = pw / max(1, len(rows) - 1)
    pts = [(left + i * step, top + ph - ph * r[1] / ymax) for i, r in enumerate(rows)]
    tpts = [(left + i * step, top + ph - ph * r[2] / ymax) for i, r in enumerate(rows)]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
           f'aria-label="AlgoLang growth by release: enterprise applications and test modules, from git tags">',
           f'<rect width="{w}" height="{h}" rx="10" fill="#FFFDF6" stroke="#E9DFB8"/>',
           f'<g transform="translate(24,30)">{logo(0, 0, 0.32)}</g>',
           f'<text x="44" y="35" font-family="{MONO}" font-size="14" fill="{NAVY}">AlgoLang growth by release</text>',
           f'<text x="{w - 20}" y="35" text-anchor="end" font-family="{SANS}" font-size="11" fill="{MUTED}">from the git tags</text>']
    for v in range(0, ymax + 1, 5 if ymax <= 30 else 10):
        y = top + ph - ph * v / ymax
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + pw}" y2="{y:.1f}" stroke="#EEE6CC"/>'
                   f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" font-family="{SANS}" font-size="11" fill="{MUTED}">{v}</text>')
    area = f"M{pts[0][0]:.1f},{top + ph} " + " ".join(f"L{x:.1f},{y:.1f}" for x, y in pts) + f" L{pts[-1][0]:.1f},{top + ph} Z"
    out.append(f'<path d="{area}" fill="{GOLD}" fill-opacity="0.12"/>')
    out.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="none" stroke="#D9534F" stroke-width="3" '
               f'stroke-linejoin="round"/>')
    out.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in tpts)}" fill="none" stroke="{NAVY}" stroke-width="2" '
               f'stroke-dasharray="5 4"/>')
    for (x, y), (t, a, _n) in zip(pts, rows):
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="#D9534F"/>')
        out.append(f'<text x="{x:.1f}" y="{top + ph + 18}" text-anchor="end" transform="rotate(-35 {x:.1f} {top + ph + 18})" '
                   f'font-family="{SANS}" font-size="11" fill="{INK}">{escape(t)}</text>')
    lx, ly = pts[-1]
    out.append(f'<text x="{lx - 6:.1f}" y="{ly - 10:.1f}" text-anchor="end" font-family="{SANS}" font-size="12" font-weight="700" '
               f'fill="#D9534F">{rows[-1][1]} applications</text>')
    out.append(f'<text x="{tpts[-1][0] - 6:.1f}" y="{tpts[-1][1] + 18:.1f}" text-anchor="end" font-family="{SANS}" font-size="12" '
               f'fill="{NAVY}">{rows[-1][2]} test modules</text>')
    out.append(f'<text x="{w / 2}" y="{h - 8}" text-anchor="middle" font-family="{SANS}" font-size="11" fill="{MUTED}">'
               f'— enterprise applications   - - test modules   ·   release</text>')
    out.append("</svg>")
    return "".join(out)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "wordmark.svg").write_text(wordmark(), encoding="utf-8")
    (OUT / "works-with.svg").write_text(works_with(), encoding="utf-8")
    (OUT / "card-release.svg").write_text(card("Latest release", "AlgoLang 1.0.0", "star"), encoding="utf-8")
    (OUT / "card-verified.svg").write_text(card("Verified in CI", "222 programs on AlgoVM", "check"), encoding="utf-8")
    (OUT / "terminal.svg").write_text(terminal(), encoding="utf-8")
    (OUT / "growth.svg").write_text(growth(), encoding="utf-8")
    print(f"header assets → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
