"""Bridge between the web playground (JavaScript) and AlgoLang (Python, running in Pyodide).

The playground unpacks algokit.zip into /home/pyodide/algokit and calls inspect() and run().
Everything runs in the visitor's browser with the offline backend: nothing is sent anywhere."""
import json
import os
import sys

HOME = "/home/pyodide/algokit"
if HOME not in sys.path:
    sys.path.insert(0, HOME)
os.environ.setdefault("ALGO_HOME", HOME)
os.chdir("/home/pyodide")

import algolang as al  # noqa: E402
from algoc import CompileError  # noqa: E402


def _diags(e):
    return [dict(code=d.code, line=d.line or 0, msg=d.msg, file=getattr(d, "file", None)) for d in e.diags]


def inspect(src):
    try:
        p = al.compile(src, "playground")
    except CompileError as e:
        return json.dumps(dict(ok=False, errors=_diags(e)))
    return json.dumps(dict(ok=True, inputs=p.inputs, agents=p.agents, tools=p.tools, errors=[]))


def run(src, inputs_json):
    try:
        p = al.compile(src, "playground")
    except CompileError as e:
        return json.dumps(dict(ok=False, compile_errors=_diags(e)))
    given = json.loads(inputs_json or "{}")
    res = p.run(quiet=True, **{k: str(given.get(k, "")) for k in p.inputs})
    d = res.to_dict()
    d["python"] = p.python
    d["escalated"] = len(res.escalated)
    try:
        with open(res.audit_path, encoding="utf-8") as f:
            d["audit"] = f.read().splitlines()[-len(res.calls) or None:] if res.calls else []
    except OSError:
        d["audit"] = []
    return json.dumps(d, default=str)


def version():
    return al.__version__
