"""
algoshell — interactive AlgoLang shell (REPL)
AlgoProfessor AI R&D Solutions · AlgoLang v0.1

Type declarations one at a time; blocks continue until their braces close.
Call an agent directly, e.g.  Explainer("neural networks"),  to run it at once.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
os.environ.setdefault("ALGO_HOME", str(HERE))

import algoruntime  # noqa: E402
from algoc import PARSER, VERSION, CompileError, compile_source, flow_graph  # noqa: E402

try:  # history and arrow keys where available (Linux/macOS)
    import readline  # noqa: F401
except ImportError:  # pragma: no cover
    pass

HELP = """\
  Type AlgoLang declarations (model, tool, agent, flow). Blocks continue until { } balance.
  Call an agent directly to run it now:   Explainer("graph neural networks")

  :run [name=value ...]   run flow main with these inputs (asks for missing ones)
  :check                  check everything defined so far
  :list                   what is defined
  :show                   print the whole program
  :graph                  show how agents feed each other in flow main
  :python                 show the generated Python
  :save FILE.algo         save the program        :load FILE.algo   load a program
  :live on|off            real Claude models (needs ANTHROPIC_API_KEY) or offline mock
  :reset                  start again             :help             this help
  :quit                   leave (Ctrl+D also works)"""

STARTER = '''model fast = "claude-haiku-5-5"'''


class Shell:
    def __init__(self):
        self.chunks: list[tuple[set, str]] = []   # (names defined, source)
        self.live = False

    # ── session ───────────────────────────────────────────────────
    def source(self):
        return "\n".join(s for _, s in self.chunks)

    @staticmethod
    def names(src):
        tree = PARSER.parse(src)
        out = set()
        for it in tree.children:
            if getattr(it, "data", "") in ("agent_decl", "flow_decl", "model_decl"):
                out.add(("model:" if it.data == "model_decl" else "") + str(it.children[0]))
        return out

    def add(self, src):
        try:
            names = self.names(src)
        except Exception:
            names = set()
        kept = [c for c in self.chunks if not (c[0] & names)]
        trial = "\n".join([s for _, s in kept] + [src])
        try:
            compile_source(trial, "shell.algo")
        except CompileError as e:
            diags = [d for d in e.diags if d.code != "E111"]
            if diags:
                off = "\n".join(s for _, s in kept).count("\n") + (1 if kept else 0)
                print(f"✗ not added — {len(diags)} error(s):")
                for d in diags:
                    ln = d.line - off
                    print(f"  {d.code} {'line ' + str(ln) + ': ' if ln >= 1 else ''}{d.msg}")
                return
        replaced = len(self.chunks) - len(kept)
        self.chunks = kept + [(names, src)]
        shown = ", ".join(sorted(n.replace("model:", "model ") for n in names)) or "declaration"
        print(f"✓ {shown}" + ("  (replaced earlier definition)" if replaced else ""))

    def compiled(self, extra=""):
        src = self.source() + ("\n" + extra if extra else "")
        try:
            return compile_source(src, "shell.algo")
        except CompileError as e:
            print(f"✗ {len(e.diags)} error(s):")
            for d in e.diags:
                print(f"  {d}")
            return None, None

    # ── running ───────────────────────────────────────────────────
    def run(self, extra="", args=None, name="shell"):
        code, prog = self.compiled(extra)
        if not code:
            return
        main = prog.flows["main"]
        vals = dict(args or {})
        for p in main.params:
            if p.name not in vals:
                vals[p.name] = input(f"{p.name}: ")
        os.environ["ALGO_HOME"] = str(HERE)
        os.environ.setdefault("ALGO_AUDIT_DIR", "runs")
        os.environ.pop("ALGO_NOTEBOOK", None)
        if self.live:
            os.environ["ALGO_LIVE"] = "1"
        else:
            os.environ.pop("ALGO_LIVE", None)
        code = code.replace("Runtime(program='shell',", f"Runtime(program={name!r},")
        ns = {"__name__": "algo_shell"}
        try:
            exec(compile(code, "<algo shell>", "exec"), ns)
            ns["flow_main"](**vals)
        except SystemExit as e:
            print(e.code)
        except algoruntime.PolicyViolation as e:
            print(f"✗ POLICY VIOLATION: {e}")
        except Exception as e:  # noqa
            print(f"✗ {type(e).__name__}: {e}")

    def quick_call(self, line):
        """Run a single agent call such as  Explainer("AI")  immediately."""
        has_main = any("main" in n for n, _ in self.chunks)
        if has_main:
            # temporarily set aside the user's main so the quick call can have its own
            saved = self.chunks
            self.chunks = [c for c in saved if "main" not in c[0]]
            self.run(f"flow main() {{ emit {line} }}", {}, name="quick")
            self.chunks = saved
        else:
            self.run(f"flow main() {{ emit {line} }}", {}, name="quick")

    # ── commands ──────────────────────────────────────────────────
    def command(self, line):
        cmd, *rest = line[1:].split(maxsplit=1)
        arg = rest[0].strip() if rest else ""
        if cmd in ("q", "quit", "exit"):
            raise EOFError
        if cmd == "help":
            print(HELP)
        elif cmd == "reset":
            self.chunks = []
            print("✓ cleared")
        elif cmd == "list":
            if not self.chunks:
                print("  (nothing defined yet)")
            for i, (n, s) in enumerate(self.chunks, 1):
                label = ", ".join(sorted(x.replace("model:", "model ") for x in n)) or s.splitlines()[0]
                print(f"  {i}. {label}")
        elif cmd == "show":
            print(self.source() or "  (empty)")
        elif cmd == "check":
            code, prog = self.compiled()
            if code:
                print(f"✓ no errors — {len(prog.agents)} agents, {len(prog.flows)} flow(s)")
        elif cmd == "python":
            code, _ = self.compiled()
            if code:
                print(code)
        elif cmd == "graph":
            code, prog = self.compiled()
            if code:
                nodes, edges = flow_graph(prog)
                label = {n: f"{l}" for n, l, *_ in nodes}
                for nid, l, kind, sub in nodes:
                    ins = [label[a] for a, b, _ in edges if b == nid]
                    mark = {"input": "◇", "agent": "■", "par": "▣", "cond": "◆", "branch": "□", "emit": "◎"}[kind]
                    feeds = f"  ← {', '.join(dict.fromkeys(ins))}" if ins else ""
                    print(f"  {mark} {l:<26} {sub:<24}{feeds}")
        elif cmd == "run":
            args = {}
            for kv in re.findall(r'(\w+)=("[^"]*"|\S+)', arg):
                args[kv[0]] = kv[1].strip('"')
            self.run("", args)
        elif cmd == "save":
            if not arg:
                print("  usage: :save myprogram.algo")
                return
            p = Path(arg if arg.endswith(".algo") else arg + ".algo")
            p.write_text(self.source() + "\n", encoding="utf-8")
            print(f"✓ saved {p}")
        elif cmd == "load":
            p = Path(arg)
            if not p.exists():
                print(f"✗ not found: {arg}")
                return
            self.chunks = []
            src = p.read_text(encoding="utf-8")
            try:
                compile_source(src, p.name)
            except CompileError as e:
                print(f"✗ {p.name} has {len(e.diags)} error(s); loaded anyway so you can fix it")
            self.chunks = [(self.names(src) if self._parses(src) else set(), src)]
            print(f"✓ loaded {p}")
        elif cmd == "live":
            self.live = arg.lower() in ("on", "1", "yes", "true")
            print(f"  backend: {'live (Claude)' if self.live else 'mock (offline)'}")
        else:
            print(f"  unknown command :{cmd} — type :help")

    @staticmethod
    def _parses(src):
        try:
            PARSER.parse(src)
            return True
        except Exception:
            return False

    # ── loop ──────────────────────────────────────────────────────
    def loop(self):
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa
                pass
        print(f"AlgoLang {VERSION} shell — every unit of work is an agent")
        print("Type :help for commands, :quit to leave. Backend: mock (offline).\n")
        buf = []
        while True:
            try:
                line = input("...> " if buf else "algo> ")
            except EOFError:
                print()
                return
            except KeyboardInterrupt:
                print("\n  (cancelled)")
                buf = []
                continue
            if not buf:
                stripped = line.strip()
                if not stripped or stripped.startswith("//"):
                    continue
                if stripped.startswith(":"):
                    try:
                        self.command(stripped)
                    except EOFError:
                        return
                    continue
                if re.match(r"^[A-Z]\w*\s*\(.*\)\s*;?$", stripped):
                    self.quick_call(stripped.rstrip(";"))
                    continue
            buf.append(line)
            text = "\n".join(buf)
            if text.count("{") <= text.count("}") and text.strip():
                self.add(text)
                buf = []


def main():
    Shell().loop()


if __name__ == "__main__":
    main()
