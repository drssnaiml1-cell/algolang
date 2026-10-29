"""Python SDK and the domain library."""
import pytest

import algolang as al


def test_version():
    assert al.__version__ == "0.2.0"


def test_catalog_has_120_packs_in_20_sectors():
    assert len(al.domains.all()) == 120
    assert len(al.domains.sectors()) == 20


@pytest.mark.parametrize("query,expected", [
    ("triage insurance claims", "insurance.claims_triage"),
    ("our servers are down and customers cannot log in", "itops.incident_triage"),
    ("screen this CV fairly", "hr.resume_screening"),
    ("check this NDA against our playbook", "legal."),
    ("cotton leaves have yellow spots", "agriculture.pest_diagnosis"),
    ("A patient with chest pain and high BP needs triage", "healthcare."),
    ("Adverse event reported after taking a new drug", "pharma."),
    ("Check this loan application for credit risk", "banking."),
    ("Summarise this quarterly earnings report for investors", "markets."),
    ("Grade these student answer scripts", "education."),
    ("Review this research manuscript for a journal", "research."),
    ("Citizen complaint: street lights in ward 12 not working", "government."),
    ("Machine on line 3 vibrating, predict maintenance", "manufacturing."),
    ("Shipment delayed at port, reroute", "supplychain."),
    ("Write product descriptions for our online store", "retail."),
    ("Phishing email reported by staff", "cyber."),
    ("Power outage in sector 5", "energy."),
    ("Plan a social media campaign for launch", "media."),
    ("Check this rental agreement and property listing", "realestate."),
    ("Guest complaint about hotel room", "hospitality."),
    ("plagiarism check for my thesis", "research.originality_check"),
])
def test_search_finds_the_right_domain(query, expected):
    assert al.domains.search(query)[0]["id"].startswith(expected)


@pytest.mark.slow
def test_every_pack_runs():
    for meta in al.domains.all():
        p = al.pack(meta["id"])
        r = p.run(**{i: "sample input for testing" for i in p.inputs})
        assert r.status in ("ok", "blocked"), (meta["id"], r.problem)
        assert r.calls, meta["id"]


def test_program_introspection():
    p = al.pack("insurance.claims_triage")
    assert p.inputs == ["claim"]
    assert "Intake" in p.agents
    g = p.graph()
    assert g["nodes"] and g["edges"]


def test_missing_input_raises():
    with pytest.raises(TypeError):
        al.pack("insurance.claims_triage").run()


def test_run_result_to_dict_is_json_safe():
    import json
    r = al.pack("insurance.claims_triage").run(claim="bumper damage")
    json.dumps(r.to_dict())


def test_compose_prompt_to_program():
    plan = al.compose("screen this CV fairly for a data analyst role")
    assert plan["best"]["id"] == "hr.resume_screening"
    r = plan["program"].run(**plan["inputs"])
    assert r.ok


def test_batch_csv(project):
    (project / "in.csv").write_text("claim\nA\nB\nC\n", encoding="utf-8")
    p = al.pack("insurance.claims_triage")
    out = al.batch_csv(p, project / "in.csv", project / "out.csv", workers=4)
    assert (project / "out.csv").exists()
    assert len(out) == 3
