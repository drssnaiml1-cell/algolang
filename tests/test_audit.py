"""Hash-chained audit log and the human review queue."""
import json

import algolang as al
from conftest import SIMPLE


def _run():
    return al.compile(SIMPLE, "audited").run(topic="AI")


def test_chain_is_valid_after_runs():
    r = _run()
    _run()
    v = al.audit.verify(r.audit_path)
    assert v["ok"] and v["records"] == 2


def test_edit_is_detected():
    r = _run()
    _run()
    lines = open(r.audit_path, encoding="utf-8").read().splitlines()
    rec = json.loads(lines[0])
    rec["tokens"] = 1
    lines[0] = json.dumps(rec)
    open(r.audit_path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    v = al.audit.verify(r.audit_path)
    assert not v["ok"] and v["first_bad_line"] == 1


def test_deletion_is_detected():
    r = _run()
    _run()
    _run()
    lines = open(r.audit_path, encoding="utf-8").read().splitlines()
    del lines[1]
    open(r.audit_path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    assert not al.audit.verify(r.audit_path)["ok"]


def test_chain_survives_parallel_batch():
    p = al.compile(SIMPLE, "parallel")
    res = p.run_batch([{"topic": f"t{i}"} for i in range(60)], workers=16)
    v = al.audit.verify(res[0].audit_path)
    assert v["ok"] and v["records"] == 60


def test_review_approve_and_reject():
    src = ('agent J(x: text) -> score { role "j" goal "score {x}" policy { require human when confidence < 0.999 } }\n'
           'flow main(x: text) { s = J(x) emit s }')
    p = al.compile(src, "rev")
    p.run(x="a")
    p.run(x="b")
    items = al.review.pending()
    assert len(items) == 2
    al.review.approve(items[0]["id"], reviewer="Dr. S", note="ok")
    al.review.reject(items[1]["id"], reviewer="Dr. S")
    assert al.review.pending() == []
    decided = {i["status"] for i in al.review.all()}
    assert decided == {"approved", "rejected"}


def test_report_totals():
    _run()
    rep = al.audit.report("runs")
    assert rep["totals"]["calls"] == 1
    assert rep["programs"]["audited"]["calls"] == 1
