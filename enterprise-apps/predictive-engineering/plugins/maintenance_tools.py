"""AlgoEng Predictive Maintenance™ tools: condition monitoring for a fleet of 1,000 centrifugal pumps.

    vib.diagnose   synthesises the pump's vibration velocity (1 s at 5 kHz, from its speed, bearing geometry and
                   hidden condition), then measures it: RMS velocity, crest factor, kurtosis, and the FFT amplitude
                   at 1× (imbalance), 2× (misalignment) and the bearing outer-race frequency (BPFO). Severity
                   zones follow ISO 10816-3 style limits for medium machines (A < 1.4, B < 2.8, C < 4.5 mm/s RMS,
                   D above).
    rul.estimate   fits exponential degradation to 26 weeks of health index (log-linear least squares) and
                   extrapolates to the failure threshold, with a 90% interval from the fit residuals
    fleet.scan     every pump at once: severity zones, fault types, and the shortest remaining lives
    maint.plan     schedules the urgent pumps across 3 crews (2 jobs per crew per day), earliest deadline first,
                   and reports any pump that cannot be reached before its predicted failure

Data: data/fleet.csv (synthetic; the true condition is used only to generate signals and to score accuracy).
"""
from __future__ import annotations

import csv
import math
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

from algoruntime import register_tool

DATA = Path(__file__).resolve().parent.parent / "data"
FS, SECONDS = 5000, 1.0
ZONES = [(1.4, "A"), (2.8, "B"), (4.5, "C"), (math.inf, "D")]
THRESHOLD = 0.5                      # health index at which a pump is expected to fail
BALLS, BALL_D, PITCH_D = 8, 7.9, 34.5   # bearing geometry (mm) for the outer-race fault frequency


@lru_cache(maxsize=1)
def fleet():
    with open(DATA / "fleet.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["rpm"], r["severity"] = float(r["rpm"]), float(r["severity"])
        r["hi"] = np.array([float(x) for x in r["health_index_26_weeks"].split()])
    return {r["asset"]: r for r in rows}


def asset_of(query):
    m = re.search(r"PMP-\d{4}", query.upper())
    return fleet().get(m.group(0)) if m else None


def bpfo(rpm):
    return BALLS / 2 * rpm / 60 * (1 - BALL_D / PITCH_D)


def signal(a):
    """Vibration velocity (mm/s) for one second, from the pump's parameters (deterministic per pump)."""
    rng = np.random.default_rng(int(a["asset"][4:]))
    t = np.arange(int(FS * SECONDS)) / FS
    f1 = a["rpm"] / 60
    s = a["severity"]
    v = 0.9 * np.sin(2 * np.pi * f1 * t) + 0.25 * np.sin(2 * np.pi * 2 * f1 * t + 0.4)
    if a["condition"] == "imbalance":
        v += 4.5 * s * np.sin(2 * np.pi * f1 * t)
    elif a["condition"] == "misalignment":
        v += 3.5 * s * np.sin(2 * np.pi * 2 * f1 * t + 1.1) + 1.2 * s * np.sin(2 * np.pi * 3 * f1 * t)
    elif a["condition"] == "bearing outer race":
        f = bpfo(a["rpm"])
        impacts = (np.sin(2 * np.pi * f * t) > 0.995).astype(float)          # short impacts at BPFO
        v += 6.0 * s * np.convolve(impacts, np.exp(-np.arange(40) / 6), "same") + 1.2 * s * np.sin(2 * np.pi * f * t)
    return v + rng.normal(0, 0.35, len(t))


def amplitude(spec, freqs, f, width=2.0):
    m = (freqs > f - width) & (freqs < f + width)
    return float(spec[m].max()) if m.any() else 0.0


def diagnose(a):
    v = signal(a)
    rms = float(np.sqrt(np.mean(v ** 2)))
    crest = float(np.max(np.abs(v)) / rms)
    kurt = float(np.mean((v - v.mean()) ** 4) / np.var(v) ** 2)
    spec = np.abs(np.fft.rfft(v * np.hanning(len(v)))) * 4 / len(v)
    freqs = np.fft.rfftfreq(len(v), 1 / FS)
    f1 = a["rpm"] / 60
    a1, a2, ab = amplitude(spec, freqs, f1), amplitude(spec, freqs, 2 * f1), amplitude(spec, freqs, bpfo(a["rpm"]))
    zone = next(z for lim, z in ZONES if rms < lim)
    if ab > 0.35 or kurt > 4.5:
        fault = "bearing outer race"
    elif a2 > 1.0 and a2 > 0.6 * a1:
        fault = "misalignment"
    elif a1 > 1.6:
        fault = "imbalance"
    else:
        fault = "healthy"
    return dict(rms=rms, crest=crest, kurt=kurt, a1=a1, a2=a2, ab=ab, zone=zone, fault=fault, f1=f1)


def rul(a):
    hi = a["hi"]
    k = np.arange(len(hi))
    y = np.log(np.clip(hi, 1e-4, None))
    slope, icpt = np.polyfit(k, y, 1)
    resid = y - (slope * k + icpt)
    sd = float(resid.std(ddof=2))
    if hi[-1] >= THRESHOLD:
        return 0.0, 0.0, 0.0, slope
    if slope <= 1e-4:
        return math.inf, math.inf, math.inf, slope
    now = len(hi) - 1

    def weeks(level_shift):
        return max(0.0, (math.log(THRESHOLD) - icpt - level_shift) / slope - now)
    return weeks(0.0), weeks(1.645 * sd), weeks(-1.645 * sd), slope


@register_tool("vib.diagnose", "Vibration diagnosis of one pump (PMP-####): RMS velocity, zone, spectrum peaks, fault type")
def vib_diagnose(query: str) -> str:
    a = asset_of(query)
    if a is None:
        return "NO ASSET: give a pump number (PMP-####)"
    d = diagnose(a)
    return (f"ZONE {d['zone']} · {d['fault'].upper()} on {a['asset']} ({a['site']}, {a['rpm']:.0f} rpm, {a['power_kw']} kW): "
            f"velocity {d['rms']:.2f} mm/s RMS\n"
            f"crest factor {d['crest']:.1f} · kurtosis {d['kurt']:.1f} · spectrum: 1× ({d['f1']:.1f} Hz) {d['a1']:.2f} · "
            f"2× {d['a2']:.2f} · BPFO ({bpfo(a['rpm']):.1f} Hz) {d['ab']:.2f} mm/s\n"
            f"zones (ISO 10816-3 style): A < 1.4 good · B < 2.8 acceptable · C < 4.5 plan repair · D act now")


@register_tool("rul.estimate", "Remaining useful life of one pump (PMP-####) from its health-index trend")
def rul_estimate(query: str) -> str:
    a = asset_of(query)
    if a is None:
        return "NO ASSET: give a pump number (PMP-####)"
    mid, lo, hi, slope = rul(a)
    if mid == 0:
        return f"FAILURE WITHIN 1 WEEK: {a['asset']} health index {a['hi'][-1]:.2f} is already at the threshold {THRESHOLD}"
    if math.isinf(mid):
        return f"STABLE: {a['asset']} shows no measurable degradation (health index {a['hi'][-1]:.3f})"
    if lo > 104:
        return (f"HEALTHY TREND: {a['asset']} remaining life more than 2 years at the current rate "
                f"(health index {a['hi'][-1]:.3f}, {100 * (math.exp(slope) - 1):.2f}% per week)")
    head = "FAILURE WITHIN 4 WEEKS" if lo <= 4 else ("FAILURE WITHIN 12 WEEKS" if lo <= 12 else "RUL")
    return (f"{head}: {a['asset']} remaining life {mid:.1f} weeks (90% interval {lo:.1f}-{hi:.1f}) to health index "
            f"{THRESHOLD}\nexponential degradation {100 * (math.exp(slope) - 1):.1f}% per week, fitted to 26 weekly "
            f"readings; now {a['hi'][-1]:.3f}")


@lru_cache(maxsize=1)
def scan():
    out = []
    for a in fleet().values():
        d = diagnose(a)
        mid, lo, _hi, _s = rul(a)
        out.append((a["asset"], d["zone"], d["fault"], a["condition"], mid, lo))
    return out


@register_tool("fleet.scan", "Scan all pumps: severity zones, fault types, accuracy, and the shortest remaining lives")
def fleet_scan(query: str) -> str:
    rows = scan()
    zones = {z: sum(1 for r in rows if r[1] == z) for z in "ABCD"}
    faults = {}
    for r in rows:
        faults[r[2]] = faults.get(r[2], 0) + 1
    correct = sum(1 for r in rows if r[2] == r[3])
    urgent = sorted((r for r in rows if r[5] <= 4), key=lambda r: r[5])
    return (f"FLEET {len(rows):,} pumps · URGENT {len(urgent)} (failure possible within 4 weeks) · zones A {zones['A']} · "
            f"B {zones['B']} · C {zones['C']} · D {zones['D']}\n"
            f"fault types: " + ", ".join(f"{k} {v}" for k, v in sorted(faults.items(), key=lambda kv: -kv[1]))
            + f" · diagnosis agrees with the recorded condition for {correct / len(rows):.1%}\n"
            f"shortest lives: " + ", ".join(f"{r[0]} {r[4]:.1f} wk ({r[2]})" for r in urgent[:6]))


@register_tool("maint.plan", "Schedule urgent pumps across 3 crews, earliest deadline first")
def maint_plan(query: str) -> str:
    rows = sorted((r for r in scan() if r[5] <= 4), key=lambda r: r[5])
    crews, per_day = 3, 2
    slots = crews * per_day
    plan, missed = [], []
    for i, r in enumerate(rows):
        day = i // slots + 1
        deadline_days = max(1, int(r[5] * 7))
        (plan if day <= deadline_days else missed).append((r[0], day, deadline_days, r[2]))
    days = (len(rows) + slots - 1) // slots
    head = (f"SCHEDULED all {len(rows)} urgent pumps in {days} working days" if not missed
            else f"CAPACITY SHORTFALL: {len(missed)} of {len(rows)} urgent pumps cannot be reached before their predicted failure")
    return (head + f" with {crews} crews × {per_day} jobs/day (earliest deadline first)\n"
            + "first jobs: " + ", ".join(f"day {d}: {a}" for a, d, _dl, _f in plan[:6])
            + (f"\nat risk: " + ", ".join(f"{a} (deadline day {dl}, slot day {d})" for a, d, dl, _f in missed[:6]) if missed else ""))
