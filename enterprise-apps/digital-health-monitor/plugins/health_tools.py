"""AlgoCare Remote Monitoring™ tools: early warning for patients monitored at home.

    vitals.news2     NEWS2 (Royal College of Physicians, 2017; SpO2 scale 1) from a reading: score per
                     parameter, total, and the clinical response band
    ehr.patient      a patient's record from the registry (PT-#####): age, conditions, medicines, last readings
    drug.check       well-known interactions among a patient's medicines (a small teaching table)
    cohort.watch     NEWS2 for all 5,000 patients' latest readings: band counts, the highest scores, and
                     patients whose score rose by 3 or more over their last three readings

Synthetic data only (data/registry.json, no names). This is decision support for clinicians, not a medical
device and not clinical advice: SpO2 scale 2 (for hypercapnic respiratory failure) and local escalation
protocols are not modelled.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from algoruntime import register_tool

DATA = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def registry():
    return json.loads((DATA / "registry.json").read_text(encoding="utf-8"))


# ───────────────────────────── NEWS2 ─────────────────────────────
def band(value, cuts):
    """cuts: list of (upper bound inclusive, points); the last bound is infinity."""
    for hi, pts in cuts:
        if value <= hi:
            return pts
    return cuts[-1][1]


INF = float("inf")


def news2(v):
    parts = {
        "respiration rate": band(v["rr"], [(8, 3), (11, 1), (20, 0), (24, 2), (INF, 3)]),
        "SpO2 (scale 1)": band(v["spo2"], [(91, 3), (93, 2), (95, 1), (INF, 0)]),
        "supplemental oxygen": 2 if v["o2"] else 0,
        "systolic BP": band(v["sbp"], [(90, 3), (100, 2), (110, 1), (219, 0), (INF, 3)]),
        "pulse": band(v["hr"], [(40, 3), (50, 1), (90, 0), (110, 1), (130, 2), (INF, 3)]),
        "consciousness": 0 if v["avpu"] == "A" else 3,
        "temperature": band(v["temp"], [(35.0, 3), (36.0, 1), (38.0, 0), (39.0, 1), (INF, 2)]),
    }
    total = sum(parts.values())
    if total >= 7:
        level, response = "HIGH RISK", "emergency assessment by a clinical team; consider transfer to hospital"
    elif total >= 5:
        level, response = "MEDIUM RISK", "urgent review by a clinician within the hour"
    elif 3 in parts.values():
        level, response = "LOW-MEDIUM RISK", "urgent review: one parameter scores 3"
    elif total >= 1:
        level, response = "LOW RISK", "nurse review; readings every 4-6 hours"
    else:
        level, response = "NO ADDED RISK", "continue routine monitoring"
    return total, level, response, parts


def parse_vitals(text):
    t = text.lower()

    def num(pattern, default):
        m = re.search(pattern, t)
        return float(m.group(1)) if m else default
    pid = re.search(r"PT-\d{5}", text.upper())
    base = dict(registry()[pid.group(0)]["readings"][-1]) if pid and pid.group(0) in registry() else \
        dict(rr=16, spo2=97, o2=False, sbp=124, hr=76, avpu="A", temp=36.8)
    v = dict(base)
    v["rr"] = num(r"(?:rr|resp(?:iratory|iration)?(?: rate)?)\D{0,6}(\d+)", base["rr"])
    v["spo2"] = num(r"(?:spo2|sats?|saturation)\D{0,6}(\d+)", base["spo2"])
    v["sbp"] = num(r"(?:bp|blood pressure|systolic)\D{0,6}(\d+)", base["sbp"])
    v["hr"] = num(r"(?:hr|pulse|heart rate)\D{0,6}(\d+)", base["hr"])
    v["temp"] = num(r"(?:temp(?:erature)?)\D{0,6}(\d+(?:\.\d+)?)", base["temp"])
    if re.search(r"\b(on oxygen|o2 \d|oxygen \d|nasal cannula|\d+ ?l/min)", t):
        v["o2"] = True
    elif re.search(r"\b(on air|room air|off oxygen)\b", t):
        v["o2"] = False
    if re.search(r"\b(confus|drows|responds to voice|responds to pain|unresponsive)", t):
        v["avpu"] = "C"
    return (pid.group(0) if pid else None), v


@register_tool("vitals.news2", "NEWS2 early-warning score and clinical response for a vital-signs reading")
def vitals_news2(query: str) -> str:
    pid, v = parse_vitals(query)
    total, level, response, parts = news2(v)
    who = f" for {pid}" if pid else ""
    return (f"NEWS2 {total} · {level}{who}: {response}\n"
            + " · ".join(f"{k} {p}" for k, p in parts.items())
            + f"\nreading: RR {v['rr']:.0f}, SpO2 {v['spo2']:.0f}%, {'oxygen' if v['o2'] else 'air'}, "
              f"BP {v['sbp']:.0f} systolic, pulse {v['hr']:.0f}, {'alert' if v['avpu'] == 'A' else 'new confusion'}, "
              f"temperature {v['temp']:.1f} °C")


@register_tool("ehr.patient", "A home-monitored patient's record (PT-#####): age, conditions, medicines, recent readings")
def ehr_patient(query: str) -> str:
    pid = re.search(r"PT-\d{5}", query.upper())
    if not pid or pid.group(0) not in registry():
        return "NO RECORD: give a registered patient number (PT-#####)"
    p = registry()[pid.group(0)]
    scores = [news2(r)[0] for r in p["readings"]]
    return (f"RECORD {pid.group(0)}: age {p['age']} · {', '.join(p['conditions'])}\n"
            f"medicines: {', '.join(p['medicines'])}\n"
            f"NEWS2 over the last three readings: {' → '.join(map(str, scores))}"
            + (" (RISING)" if scores[-1] - scores[0] >= 3 else ""))


INTERACTIONS = {
    frozenset({"warfarin", "aspirin"}): ("MAJOR", "bleeding risk"),
    frozenset({"warfarin", "ibuprofen"}): ("MAJOR", "bleeding risk"),
    frozenset({"warfarin", "clarithromycin"}): ("MAJOR", "raised INR, bleeding risk"),
    frozenset({"lisinopril", "spironolactone"}): ("MAJOR", "high potassium (hyperkalaemia)"),
    frozenset({"simvastatin", "clarithromycin"}): ("MAJOR", "muscle damage (rhabdomyolysis); avoid together"),
    frozenset({"sertraline", "tramadol"}): ("MAJOR", "serotonin syndrome and seizure risk"),
    frozenset({"digoxin", "amiodarone"}): ("MAJOR", "digoxin toxicity"),
    frozenset({"clopidogrel", "omeprazole"}): ("MODERATE", "reduced antiplatelet effect"),
    frozenset({"sertraline", "aspirin"}): ("MODERATE", "bleeding risk"),
    frozenset({"lisinopril", "ibuprofen"}): ("MODERATE", "reduced BP control, kidney strain"),
    frozenset({"furosemide", "digoxin"}): ("MODERATE", "low potassium raises digoxin toxicity"),
}


@register_tool("drug.check", "Known interactions among a patient's medicines (PT-##### or a list of medicines)")
def drug_check(query: str) -> str:
    pid = re.search(r"PT-\d{5}", query.upper())
    if pid and pid.group(0) in registry():
        meds = registry()[pid.group(0)]["medicines"]
    else:
        names = {m for pair in INTERACTIONS for m in pair}
        meds = sorted(m for m in names if m in query.lower())
    found = []
    for i, a in enumerate(meds):
        for b in meds[i + 1:]:
            hit = INTERACTIONS.get(frozenset({a, b}))
            if hit:
                found.append((hit[0], a, b, hit[1]))
    found.sort(key=lambda f: f[0] != "MAJOR")
    if not found:
        return f"NO KNOWN INTERACTION among {', '.join(meds) or 'the medicines given'} (teaching table only)"
    head = "MAJOR INTERACTION" if found[0][0] == "MAJOR" else "MODERATE INTERACTION"
    return (f"{head}: " + "; ".join(f"{a} + {b} ({sev.lower()}: {why})" for sev, a, b, why in found)
            + " · teaching table only; confirm with a pharmacist")


@register_tool("cohort.watch", "NEWS2 across all home-monitored patients: bands, highest scores, rising trends")
def cohort_watch(query: str) -> str:
    reg = registry()
    counts, top, rising = {}, [], []
    for pid, p in reg.items():
        scores = [news2(r)[0] for r in p["readings"]]
        lvl = news2(p["readings"][-1])[1]
        counts[lvl] = counts.get(lvl, 0) + 1
        top.append((scores[-1], pid))
        if scores[-1] - scores[0] >= 3:
            rising.append((scores[-1] - scores[0], pid, scores))
    top.sort(reverse=True)
    rising.sort(reverse=True)
    order = ["HIGH RISK", "MEDIUM RISK", "LOW-MEDIUM RISK", "LOW RISK", "NO ADDED RISK"]
    return (f"COHORT {len(reg):,} patients · RISING {len(rising)} · "
            + " · ".join(f"{k.lower()} {counts.get(k, 0):,}" for k in order) + "\n"
            f"highest NEWS2: " + ", ".join(f"{pid} ({s})" for s, pid in top[:6]) + "\n"
            f"rising by 3 or more points over three readings: {len(rising)} patients, e.g. "
            + ", ".join(f"{pid} {' → '.join(map(str, sc))}" for _d, pid, sc in rising[:4]))
