"""Run every enterprise application's behaviour tests (and, with --batch, its sample batch job).

    python enterprise-apps/run_all.py            # tests only
    python enterprise-apps/run_all.py --batch    # tests + batch over data/*.csv + audit verification

Each app runs in its own folder, so its algo.config.json and company plugins load.
Exit code 0 when everything passes.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALGOC = HERE.parent / "algoc.py"
BATCH = {
    "claims-ops-center": ("claims_intake.algo", "claims_batch.csv"),
    "hospital-care-coordination": ("er_triage.algo", "er_notes.csv"),
    "bank-credit-onboarding": ("loan_decision.algo", "loan_applications.csv"),
    "university-admissions-obe": ("admissions.algo", "applications.csv"),
    "soc-incident-command": ("alert_to_incident.algo", "alerts.csv"),
    "supply-chain-control-tower": ("exception_desk.algo", "exceptions.csv"),
    "citizen-services-desk": ("grievance_desk.algo", "grievances.csv"),
    "legal-contract-desk": ("nda_triage.algo", "ndas.csv"),
}


def run(args, cwd, env):
    return subprocess.run([sys.executable, str(ALGOC), *args], cwd=cwd, env=env, capture_output=True, text=True)


def main():
    batch = "--batch" in sys.argv
    env = dict(os.environ, NO_COLOR="1", PYTHONIOENCODING="utf-8")
    failed, rows = 0, []
    for app in sorted(p for p in HERE.iterdir() if (p / "algo.config.json").exists()):
        tmp = tempfile.mkdtemp(prefix=f"algo-{app.name}-")
        env_app = dict(env, ALGO_AUDIT_DIR=tmp)
        r = run(["dev", "test", "tests", "--json"], app, env_app)
        try:
            res = json.loads(r.stdout[r.stdout.index("{"):])
            cases, bad = res["cases"], res["failed"]
        except (ValueError, KeyError):
            cases, bad = 0, 1
            print(r.stdout, r.stderr)
        status = "ok" if bad == 0 and r.returncode == 0 else "FAIL"
        extra = ""
        if batch and app.name in BATCH:
            prog, csv_file = BATCH[app.name]
            out = Path(tmp) / "results.csv"
            b = run(["batch", f"programs/{prog}", "--input", f"data/{csv_file}", "--workers", "8", "--out", str(out)], app, env_app)
            v = run(["audit", "verify", tmp], app, env_app)
            ok = b.returncode == 0 and v.returncode == 0 and out.exists()
            rows_done = max(0, len(out.read_text(encoding="utf-8").splitlines()) - 1) if out.exists() else 0
            extra = f"  batch {rows_done} rows, audit {'intact' if v.returncode == 0 else 'BROKEN'}"
            if not ok:
                status, bad = "FAIL", bad + 1
                print(b.stdout[-800:], b.stderr[-800:], v.stdout[-400:])
        failed += bad
        rows.append(f"  {'✓' if status == 'ok' else '✗'} {app.name:<28} {cases - (bad if status != 'ok' else 0)}/{cases} tests{extra}")
        if status != "ok":
            print(r.stdout[-1500:])
    print("AlgoLang enterprise applications")
    print("\n".join(rows))
    print(f"\n  {'all applications pass' if not failed else str(failed) + ' failure(s)'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
