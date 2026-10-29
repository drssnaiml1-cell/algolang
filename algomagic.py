"""
algomagic — run AlgoLang inside Jupyter Notebook, JupyterLab and Google Colab.
AlgoProfessor AI R&D Solutions · AlgoLang v0.1

    %load_ext algomagic

    %%algo --arg "topic=Neural networks"      run a whole program in one cell
    %%algo --define                           add agents/models/tools to the session
    %%algo --check                            only check for errors
    %%algo --graph                            also draw the flow as a diagram
    %%algo --python                           also show the generated Python
    %%algo --live                             call real Claude models
    %%algo --interactive                      ask a human to approve low-confidence results

    %algo_run examples/research_brief.algo --arg "topic=..."   run a .algo file
    %algo_list     what is defined in this session
    %algo_reset    forget all --define cells
    %algo_help     this help

After a run, these Python variables are set:
    algo_result   list of values the flow emitted
    algo_calls    list of dicts, one per agent call (agent, model, confidence, status, tokens, output…)
"""
from __future__ import annotations

import argparse
import html
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
os.environ.setdefault("ALGO_HOME", str(HERE))

from IPython.core.magic import Magics, cell_magic, line_magic, magics_class  # noqa: E402
from IPython.display import HTML, Markdown, display  # noqa: E402

import algoruntime  # noqa: E402
from algoc import PARSER, VERSION, CompileError, compile_source, flow_graph  # noqa: E402

CSS = """<style>
.algo-box{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;border:1px solid #0b1f3a;
  border-left:6px solid #c9a227;border-radius:6px;background:#ffffff;color:#1b1b1b;margin:8px 0;
  overflow:hidden;max-width:1000px}
.algo-head{background:#0b1f3a;color:#ffffff;padding:7px 12px;font-weight:600;font-size:13px;letter-spacing:.2px}
.algo-head b{color:#c9a227}
.algo-body{padding:8px 12px;font-size:13px;line-height:1.45;color:#1b1b1b}
.algo-box table{border-collapse:collapse;width:100%;font-size:12.5px}
.algo-box th{background:#f3efe1;color:#0b1f3a;text-align:left;padding:5px 8px;border-bottom:2px solid #c9a227}
.algo-box td{padding:5px 8px;border-bottom:1px solid #e6e6e6;vertical-align:top;color:#1b1b1b}
.algo-err{border-color:#7a1020;border-left-color:#7a1020}
.algo-err .algo-head{background:#7a1020}
.algo-ok{color:#1d6b35;font-weight:600}.algo-warn{color:#9a5b00;font-weight:600}.algo-bad{color:#a01020;font-weight:600}
.algo-box code{background:#f4f4f4;padding:1px 4px;border-radius:3px;color:#0b1f3a}
.algo-lanes{display:flex;gap:10px;align-items:flex-start;overflow-x:auto;padding:4px 0}
.algo-lane{display:flex;flex-direction:column;gap:8px;min-width:112px;max-width:150px;flex:1 1 0}
.algo-node{border-radius:6px;padding:6px 9px;font-size:12px}
.algo-node small{display:block;opacity:.8;font-size:10.5px;margin-top:2px}
.n-input{background:#f3efe1;color:#0b1f3a;border:1px solid #c9a227}
.n-agent{background:#0b1f3a;color:#fff}
.n-par{background:#1d3b66;color:#fff;border:2px solid #c9a227}
.n-cond{background:#c9a227;color:#0b1f3a;font-weight:600}
.n-branch{background:#fff;color:#0b1f3a;border:1.5px dashed #0b1f3a}
.n-emit{background:#fff;color:#0b1f3a;border:2px solid #c9a227;font-weight:600}
.n-op{background:#eef1f6;color:#0b1f3a}
</style>"""


def _box(title, body, kind="ok"):
    cls = "algo-box algo-err" if kind == "err" else "algo-box"
    display(HTML(f'{CSS}<div class="{cls}"><div class="algo-head">{title}</div>'
                 f'<div class="algo-body">{body}</div></div>'))


def _esc(x, n=None):
    s = str(x)
    if n and len(s) > n:
        s = s[:n] + "…"
    return html.escape(s)


def _fmt_value(v):
    v = algoruntime.Runtime.value(v)
    if isinstance(v, list):
        items = "".join(f"<li>{_esc(algoruntime.Runtime.value(x))}</li>" for x in v)
        return f"<ol style='margin:0;padding-left:18px'>{items}</ol>"
    return _esc(v)


# ─────────────────────────── the magics ───────────────────────────
@magics_class
class AlgoMagics(Magics):
    def __init__(self, shell):
        super().__init__(shell)
        self.chunks: list[tuple[set, str]] = []   # (names defined, source) from --define cells

    # helpers ----------------------------------------------------------
    @staticmethod
    def _names(src):
        tree = PARSER.parse(src)
        return {str(it.children[0]) for it in tree.children
                if getattr(it, "data", "") in ("agent_decl", "flow_decl")}

    def _compile(self, chunks, cell, name, define=False):
        prefix = "\n".join(s for _, s in chunks)
        src = prefix + ("\n" if prefix else "") + cell
        off = prefix.count("\n") + (1 if prefix else 0)
        try:
            code, prog = compile_source(src, f"{name}.algo")
            return code, prog, [], off
        except CompileError as e:
            diags = [d for d in e.diags if not (define and d.code == "E111")]
            return None, None, diags, off

    def _show_diags(self, diags, off):
        rows = []
        for d in diags:
            ln = d.line - off
            where = f"line {ln}" if ln >= 1 else "an earlier <code>--define</code> cell"
            msg = _esc(d.msg).replace("\n", "<br>")
            rows.append(f"<tr><td><b>{d.code}</b></td><td>{where}</td><td>{msg}</td></tr>")
        _box(f"✗ <b>{len(diags)}</b> compile error(s) — nothing was run",
             f"<table><tr><th>Code</th><th>Where</th><th>Problem</th></tr>{''.join(rows)}</table>", "err")

    def _parse_line(self, line, run=True):
        ap = argparse.ArgumentParser(prog="%%algo", add_help=False)
        ap.add_argument("--define", action="store_true")
        ap.add_argument("--check", action="store_true")
        ap.add_argument("--arg", action="append", default=[])
        ap.add_argument("--live", action="store_true")
        ap.add_argument("--interactive", action="store_true")
        ap.add_argument("--graph", action="store_true")
        ap.add_argument("--python", action="store_true")
        ap.add_argument("--name", default="notebook")
        try:
            a, rest = ap.parse_known_args(shlex.split(line))
        except SystemExit:
            _box("✗ could not read the options", "Example: <code>%%algo --arg \"topic=AI ethics\" --graph</code>", "err")
            return None, []
        return a, rest

    # %%algo ------------------------------------------------------------
    @cell_magic
    def algo(self, line, cell):
        a, rest = self._parse_line(line)
        if a is None:
            return
        if rest:
            _box("✗ unknown option", f"<code>{_esc(' '.join(rest))}</code> — see <code>%algo_help</code>", "err")
            return
        if a.define:
            return self._define(cell)
        self._run(cell, a, chunks=self.chunks)

    def _define(self, cell):
        try:
            names = self._names(cell)
        except Exception:  # noqa — let the compiler produce the proper E100 message
            names = set()
        kept = [c for c in self.chunks if not (c[0] & names)]
        _, _, diags, off = self._compile(kept, cell, "notebook", define=True)
        if diags:
            return self._show_diags(diags, off)
        replaced = len(self.chunks) - len(kept)
        self.chunks = kept + [(names, cell)]
        total = set().union(*(c[0] for c in self.chunks)) if self.chunks else set()
        what = ", ".join(f"<code>{n}</code>" for n in sorted(names)) or "models / tools"
        note = " (replaced the earlier definition)" if replaced else ""
        _box(f"✓ defined {what}{note}",
             f"Session now has {len(total)} agent(s)/flow(s). Run a cell with <code>flow main</code> to use them.")

    def _run(self, cell, a, chunks):
        code, prog, diags, off = self._compile(chunks, cell, a.name)
        if diags:
            return self._show_diags(diags, off)
        if a.check:
            return _box("✓ no errors",
                        f"{len(prog.agents)} agent(s) · {len(prog.flows)} flow(s) · {len(prog.tools)} tool(s)")
        if a.python:
            display(Markdown(f"**Generated Python**\n\n```python\n{code}\n```"))
        if a.graph:
            self._graph(prog)

        main = prog.flows["main"]
        vals = {}
        for kv in a.arg:
            if "=" not in kv:
                return _box("✗ bad --arg", f"Use <code>--arg \"name=value\"</code>; got <code>{_esc(kv)}</code>", "err")
            k, v = kv.split("=", 1)
            vals[k.strip()] = v
        for p in main.params:
            if p.name not in vals:
                vals[p.name] = input(f"{p.name}: ")
        unknown = set(vals) - {p.name for p in main.params}
        if unknown:
            return _box("✗ unknown input", f"flow main has no input {', '.join(map(_esc, unknown))}", "err")

        os.environ["ALGO_HOME"] = str(HERE)
        os.environ["ALGO_NOTEBOOK"] = "1"     # runtime prints progress only; the table shows results
        os.environ.setdefault("ALGO_AUDIT_DIR", "runs")
        for var, on in (("ALGO_LIVE", a.live), ("ALGO_INTERACTIVE", a.interactive)):
            if on:
                os.environ[var] = "1"
            else:
                os.environ.pop(var, None)

        ns = {"__name__": "algo_notebook"}
        try:
            exec(compile(code, f"<algo:{a.name}>", "exec"), ns)
        except SystemExit as e:   # e.g. --live without a key
            return _box("✗ could not start", _esc(e.code), "err")

        rt, result, problem = ns["rt"], None, None
        try:
            result = ns["flow_main"](**vals)
        except algoruntime.PolicyViolation as e:
            problem = ("✗ policy violation — run stopped", _esc(e))
        except Exception as e:  # noqa
            problem = ("✗ an agent call failed", f"{_esc(type(e).__name__)}: {_esc(e, 400)}")

        self.shell.user_ns["algo_result"] = result
        self.shell.user_ns["algo_calls"] = rt.calls
        self._summary(rt, result, problem)

    def _summary(self, rt, result, problem):
        rows = []
        for c in rt.calls:
            st = c.get("status")
            cls = {"ok": "algo-ok", "approved": "algo-ok", "escalated": "algo-warn"}.get(st, "algo-bad")
            label = {"escalated": "⚠ human review", "approved": "✔ approved", "ok": "ok"}.get(st, st)
            conf = f"{c['confidence']:.2f}" if "confidence" in c else "—"
            out = c.get("output")
            out = _fmt_value(out) if out is not None else _esc(c.get("reason") or c.get("error") or "")
            rows.append(f"<tr><td><b>{_esc(c.get('agent'))}</b></td>"
                        f"<td style='white-space:nowrap'>{_esc(c.get('model', '—'))}</td>"
                        f"<td>{conf}</td><td class='{cls}'>{_esc(label)}</td><td>{c.get('tokens', '—')}</td>"
                        f"<td>{out}</td></tr>")
        s = rt.stats
        body = (f"<table><tr><th>Agent</th><th>Model</th><th>Conf.</th><th>Status</th><th>Tokens</th>"
                f"<th>Output</th></tr>{''.join(rows)}</table>")
        if problem:
            body = f"<p class='algo-bad'>{problem[1]}</p>" + body
        elif result is not None:
            emitted = "".join(f"<li style='margin-bottom:4px'>{_fmt_value(v)}</li>" for v in result)
            body += f"<p style='margin:10px 0 4px'><b>Emitted</b> (also in <code>algo_result</code>)</p><ol>{emitted}</ol>"
        head = problem[0] if problem else "✓ run complete"
        head += (f" · <b>{s['calls']}</b> agent calls · ~{s['tokens']} tokens · {s['escalations']}"
                 f" escalated · backend <b>{rt.backend.name}</b>")
        _box(head, body + f"<p style='margin:8px 0 0;font-size:11.5px;color:#555'>audit log: "
                          f"<code>{_esc(rt.audit_path)}</code> · run {rt.run_id}</p>",
             "err" if problem else "ok")

    # flow diagram -----------------------------------------------------
    def _graph(self, prog):
        nodes, edges = flow_graph(prog)

        if shutil.which("dot"):
            try:
                import graphviz
                style = {
                    "input": dict(shape="oval", style="filled", fillcolor="#f3efe1", color="#c9a227", fontcolor="#0b1f3a"),
                    "agent": dict(shape="box", style="rounded,filled", fillcolor="#0b1f3a", fontcolor="white", color="#0b1f3a"),
                    "par": dict(shape="box", style="rounded,filled", fillcolor="#1d3b66", fontcolor="white", color="#c9a227", penwidth="2"),
                    "cond": dict(shape="diamond", style="filled", fillcolor="#c9a227", fontcolor="#0b1f3a", color="#c9a227"),
                    "branch": dict(shape="box", style="rounded,dashed", fontcolor="#0b1f3a", color="#0b1f3a"),
                    "emit": dict(shape="oval", style="bold", color="#c9a227", fontcolor="#0b1f3a"),
                }
                g = graphviz.Digraph(graph_attr=dict(rankdir="LR", bgcolor="white", fontname="Helvetica", pad="0.2"),
                                     node_attr=dict(fontname="Helvetica", fontsize="11"),
                                     edge_attr=dict(color="#0b1f3a", arrowsize="0.7"))
                for nid, label, kind, sub in nodes:
                    g.node(nid, f"{label}\n{sub}" if sub else label, **style[kind])
                for a, b, dashed in edges:
                    g.edge(a, b, style="dashed" if dashed else "solid")
                svg = g.pipe(format="svg").decode()
                svg = svg[svg.index("<svg"):]                      # drop XML prolog / doctype
                svg = re.sub(r'<svg width="[^"]*" height="[^"]*"',
                             '<svg style="width:100%;max-width:960px;height:auto"', svg, count=1)
                display(HTML(f"{CSS}<div class='algo-box'><div class='algo-head'>flow <b>main</b> — agent graph</div>"
                             f"<div class='algo-body'>{svg}</div></div>"))
                return
            except Exception:  # noqa — fall back to the HTML layout
                pass
        # dependency-free fallback: columns by depth, each node lists what feeds it
        depth = {}
        for nid, *_ in nodes:
            ins = [a for a, b, _ in edges if b == nid]
            depth[nid] = 1 + max((depth.get(a, 0) for a in ins), default=-1)
        label_of = {nid: label for nid, label, *_ in nodes}
        lanes = {}
        for nid, label, kind, sub in nodes:
            ins = [label_of[a] for a, b, _ in edges if b == nid]
            feeds = f"<small>← {_esc(', '.join(dict.fromkeys(ins)))}</small>" if ins else ""
            subl = f"<small>{_esc(sub)}</small>" if sub else ""
            lanes.setdefault(depth[nid], []).append(f"<div class='algo-node n-{kind}'>{_esc(label)}{subl}{feeds}</div>")
        cols = "".join(f"<div class='algo-lane'>{''.join(v)}</div>" for _, v in sorted(lanes.items()))
        _box("flow <b>main</b> — agent graph (left → right)", f"<div class='algo-lanes'>{cols}</div>")

    # line magics -------------------------------------------------------
    @line_magic
    def algo_run(self, line):
        parts = shlex.split(line)
        if not parts:
            return _box("✗ which file?", "Example: <code>%algo_run examples/research_brief.algo --arg \"topic=AI\"</code>", "err")
        path = Path(parts[0])
        if not path.exists() and (HERE / path).exists():
            path = HERE / path
        if not path.exists():
            return _box("✗ file not found", _esc(parts[0]), "err")
        a, rest = self._parse_line(shlex.join(parts[1:]))
        if a is None:
            return
        a.name = path.stem
        self._run(path.read_text(encoding="utf-8"), a, chunks=[])

    @line_magic
    def algo_list(self, line):
        if not self.chunks:
            return _box("session is empty", "Use <code>%%algo --define</code> to add agents.")
        rows = "".join(f"<tr><td>{i + 1}</td><td>{', '.join(sorted(n)) or '(models / tools)'}</td>"
                       f"<td>{s.count(chr(10)) + 1} lines</td></tr>" for i, (n, s) in enumerate(self.chunks))
        _box("session definitions", f"<table><tr><th>#</th><th>Defines</th><th>Size</th></tr>{rows}</table>")

    @line_magic
    def algo_reset(self, line):
        self.chunks = []
        _box("✓ session cleared", "All <code>--define</code> cells were forgotten.")

    @line_magic
    def algo_help(self, line):
        display(Markdown(f"```text\n{__doc__}\n```"))


def load_ipython_extension(ip):
    ip.register_magics(AlgoMagics)
    _box(f"AlgoLang <b>{VERSION}</b> ready",
         "Write AlgoLang in any cell that starts with <code>%%algo</code>. "
         "Options: <code>--arg \"name=value\"</code> · <code>--define</code> · <code>--graph</code> · "
         "<code>--check</code> · <code>--python</code> · <code>--interactive</code> · <code>--live</code>. "
         "Help: <code>%algo_help</code>")
