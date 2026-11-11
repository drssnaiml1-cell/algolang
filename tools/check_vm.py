"""Run every shipped program (domain packs, examples, enterprise apps) on compiled Python and on the AlgoVM,
and require identical results: status, emitted values and number of agent calls (v1.0)."""
import glob
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import algoir  # noqa: E402
import algolang as al  # noqa: E402
import algoruntime as rt  # noqa: E402

DUMMY = {"text": "Asha Rao asks about INR 48,000 claim POL-1001", "score": 0.6, "list": "alpha; beta", "bool": "true",
         "json": '{"k": 1}', "number": 5}


def main():
    files = sorted(glob.glob(f"{ROOT}/packs/**/*.algo", recursive=True) + glob.glob(f"{ROOT}/examples/**/*.algo", recursive=True)
                   + glob.glob(f"{ROOT}/enterprise-apps/*/programs/*.algo"))
    files = [f for f in files if f"{os.sep}build{os.sep}" not in f and "/build/" not in f]
    ok, bad = 0, []
    for f in files:
        p = Path(f)
        app = p.parent.parent if p.parent.name == "programs" else p.parent
        os.chdir(app)
        rt._CONFIG = None
        rt.load_config(reload=True)
        try:
            prog_sdk = al.load(f)
        except Exception:  # noqa — library files without flow main
            continue
        prog = prog_sdk._prog
        if "main" not in prog.flows:
            continue
        ev = next((e for e in prog.evals if e.flow == "main" and e.cases), None)
        inputs = ev.cases[0].inputs if ev else {x.name: DUMMY.get(x.type.replace("uncertain<", "").rstrip(">"), "x")
                                                for x in prog.flows["main"].params}
        doc = algoir.to_ir(prog, p.stem, p.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            a = prog_sdk.run(audit_dir=t1, **inputs)
            b = algoir.IRProgram(doc, f).run(audit_dir=t2, **inputs)
        va = json.dumps([rt._jsonable(rt.Runtime.value(v)) for v in a.values], sort_keys=True, default=str)
        vb = json.dumps([rt._jsonable(rt.Runtime.value(v)) for v in b.values], sort_keys=True, default=str)
        if (a.status, va, len(a.calls)) == (b.status, vb, len(b.calls)):
            ok += 1
        else:
            bad.append(f)
            print(f"✗ {Path(f).relative_to(ROOT)}: python {a.status} {va[:80]} | vm {b.status} {vb[:80]}")
    print(f"AlgoVM equivalence: {ok} programs identical, {len(bad)} different")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
