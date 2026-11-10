"""AlgoCity Operations Centre™ tools: air quality, waste collection and electricity for a smart city.

    city.aqi     India's National Air Quality Index (CPCB method): a sub-index per pollutant by linear
                 interpolation within the official breakpoints, the AQI is the worst sub-index (at least three
                 pollutants, one of them PM2.5 or PM10); city summary by zone and station
    city.waste   sensor-driven waste collection: bins at least 75% full, a route from the depot by nearest
                 neighbour improved with 2-opt, truck capacity, compared with the fixed route through every bin
    city.reading AQI of a single live sensor reading (used by the AlgoPulse sensor stream)
    city.energy  next-day feeder load: seasonal (weekly-hour) profile with exponential smoothing of the level,
                 back-tested on the last week (MAPE), with the predicted peak against the feeder's 60 MW limit

Data (data/): air_stations.csv for three days, bins.json (400 bins, km coordinates), feeder_load.csv (8 weeks,
hourly, normal and heatwave). All synthetic.
"""
from __future__ import annotations

import csv
import json
import math
import re
from functools import lru_cache
from pathlib import Path

from algoruntime import register_tool

DATA = Path(__file__).resolve().parent.parent / "data"

# CPCB National AQI breakpoints (concentration bands for AQI 0-50, 51-100, 101-200, 201-300, 301-400, 401-500)
BREAKS = {
    "pm10": [(0, 50), (51, 100), (101, 250), (251, 350), (351, 430), (431, 600)],
    "pm25": [(0, 30), (31, 60), (61, 90), (91, 120), (121, 250), (251, 380)],
    "no2": [(0, 40), (41, 80), (81, 180), (181, 280), (281, 400), (401, 600)],
    "o3": [(0, 50), (51, 100), (101, 168), (169, 208), (209, 748), (749, 1000)],
    "co": [(0, 1.0), (1.1, 2.0), (2.1, 10), (10.1, 17), (17.1, 34), (34.1, 50)],
    "so2": [(0, 40), (41, 80), (81, 380), (381, 800), (801, 1600), (1601, 2400)],
    "nh3": [(0, 200), (201, 400), (401, 800), (801, 1200), (1201, 1800), (1801, 2400)],
}
INDEX = [(0, 50), (51, 100), (101, 200), (201, 300), (301, 400), (401, 500)]
CATS = ["Good", "Satisfactory", "Moderately polluted", "Poor", "Very poor", "Severe"]
LABEL = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO2", "so2": "SO2", "co": "CO", "o3": "O3", "nh3": "NH3"}


def sub_index(pollutant, c):
    bands = BREAKS[pollutant]
    for (lo, hi), (ilo, ihi) in zip(bands, INDEX):
        if c <= hi:
            return ilo + (ihi - ilo) * (max(c, lo) - lo) / (hi - lo)
    return 500.0


def aqi(row):
    subs = {p: sub_index(p, float(row[p])) for p in BREAKS}
    worst = max(subs, key=subs.get)
    value = round(subs[worst])
    cat = CATS[next(i for i, (lo, hi) in enumerate(INDEX) if value <= hi)]
    return value, cat, LABEL[worst]


@lru_cache(maxsize=1)
def stations():
    with open(DATA / "air_stations.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def day_of(query):
    q = query.lower()
    if "diwali" in q:
        return "post-diwali"
    if "monsoon" in q or "july" in q:
        return "monsoon"
    return "winter-weekday"


@register_tool("city.aqi", "National Air Quality Index (CPCB method) for every station and zone on a given day")
def city_aqi(query: str) -> str:
    day = day_of(query)
    rows = [r for r in stations() if r["day"] == day]
    res = [(r["station"], r["zone"], *aqi(r)) for r in rows]
    worst = max(res, key=lambda x: x[2])
    zones = {}
    for _s, z, v, _c, _p in res:
        zones.setdefault(z, []).append(v)
    zone_line = " · ".join(f"{z} {max(v)}" for z, v in sorted(zones.items(), key=lambda kv: -max(kv[1])))
    counts = {c: sum(1 for x in res if x[3] == c) for c in CATS}
    city_cat = worst[3].upper()
    return (f"AQI {city_cat} at worst ({worst[2]} at {worst[0]}, {worst[1]}; driven by {worst[4]}) on the {day} day\n"
            f"{len(res)} stations: " + ", ".join(f"{c.lower()} {n}" for c, n in counts.items() if n) + "\n"
            f"worst station per zone: {zone_line}\n"
            "method: CPCB National AQI, sub-index by linear interpolation within the official breakpoints; AQI is the worst sub-index")


def tour_length(pts, order):
    return sum(math.dist(pts[order[i]], pts[order[i + 1]]) for i in range(len(order) - 1))


def route(pts):
    """Nearest neighbour from the depot (index 0), then 2-opt until no improving swap; returns to the depot."""
    left = set(range(1, len(pts)))
    order = [0]
    while left:
        nxt = min(left, key=lambda j: math.dist(pts[order[-1]], pts[j]))
        order.append(nxt)
        left.remove(nxt)
    order.append(0)
    improved = True
    while improved:
        improved = False
        for i in range(1, len(order) - 2):
            for j in range(i + 1, len(order) - 1):
                a, b, c, d = pts[order[i - 1]], pts[order[i]], pts[order[j]], pts[order[j + 1]]
                if math.dist(a, c) + math.dist(b, d) < math.dist(a, b) + math.dist(c, d) - 1e-9:
                    order[i:j + 1] = reversed(order[i:j + 1])
                    improved = True
    return order


@register_tool("city.waste", "Route waste trucks to smart bins that are at least 75% full (nearest neighbour + 2-opt)")
def city_waste(query: str) -> str:
    d = json.loads((DATA / "bins.json").read_text(encoding="utf-8"))
    full = [b for b in d["bins"] if b["fill"] >= 0.75]
    cap = d["truck_capacity_bins"]
    trucks = math.ceil(len(full) / cap)
    full.sort(key=lambda b: math.atan2(b["y"] - d["depot"][1], b["x"] - d["depot"][0]))     # sweep into truck sectors
    total, legs = 0.0, []
    for t in range(trucks):
        group = full[t * cap:(t + 1) * cap]
        pts = [tuple(d["depot"])] + [(b["x"], b["y"]) for b in group]
        order = route(pts)
        km = tour_length(pts, order)
        total += km
        legs.append(f"truck {t + 1}: {len(group)} bins, {km:.1f} km")
    allpts = [tuple(d["depot"])] + [(b["x"], b["y"]) for b in d["bins"]]
    fixed = tour_length(allpts, route(allpts))
    saving = 1 - total / fixed
    return (f"ROUTES {trucks} truck(s) for {len(full)} of {len(d['bins'])} bins at 75%+ full · {total:.1f} km vs "
            f"{fixed:.1f} km for the fixed route through every bin (−{saving:.0%})\n" + " · ".join(legs)
            + "\nmethod: angular sweep into truck loads, nearest neighbour from the depot, 2-opt improvement")


@lru_cache(maxsize=1)
def load():
    out = {}
    with open(DATA / "feeder_load.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.setdefault(r["scenario"], []).append(float(r["mw"]))
    return out


def forecast(series, horizon=24, alpha=0.3):
    """Weekly-hour seasonal profile (mean of past weeks) plus an exponentially smoothed level correction."""
    week = 168
    n = len(series)
    weeks = n // week
    prof = [sum(series[w * week + h] for w in range(weeks)) / weeks for h in range(week)]
    level = 0.0
    for t in range(n - week, n):
        level = alpha * (series[t] - prof[t % week]) + (1 - alpha) * level
    return [prof[(n + k) % week] + level for k in range(horizon)]


@register_tool("city.energy", "Next-day feeder load forecast with back-test error and the 60 MW overload check")
def city_energy(query: str) -> str:
    scen = "heatwave" if "heat" in query.lower() else "normal"
    s = load()[scen]
    train, test = s[:-168], s[-168:]
    preds = []
    for d in range(7):                                   # back-test: forecast each day of the last week from the past
        preds += forecast(s[:len(train) + 24 * d], 24)
    mape = sum(abs(p - a) / a for p, a in zip(preds, test)) / len(test)
    nxt = forecast(s, 24)
    peak = max(nxt)
    hour = nxt.index(peak)
    limit = 60.0
    head = (f"OVERLOAD RISK: tomorrow's peak {peak:.1f} MW at {hour:02d}:00 is above the {limit:.0f} MW feeder limit"
            if peak > limit * 0.97 else f"WITHIN LIMIT: tomorrow's peak {peak:.1f} MW at {hour:02d}:00 (limit {limit:.0f} MW)")
    return (head + f" · {scen} weeks\nback-test on the last 7 days: MAPE {mape:.1%} · method: weekly-hour profile + "
            f"exponentially smoothed level (alpha 0.3)")


READING = re.compile(r"(PM2\.?5|PM10|NO2|SO2|CO|O3|NH3)\s*[:=]?\s*(\d+(?:\.\d+)?)", re.I)
KEYS = {"PM2.5": "pm25", "PM25": "pm25", "PM10": "pm10", "NO2": "no2", "SO2": "so2", "CO": "co", "O3": "o3", "NH3": "nh3"}


@register_tool("city.reading", "AQI of one live sensor reading (e.g. 'AQ-12 PM2.5 140 PM10 220 NO2 60')")
def city_reading(query: str) -> str:
    vals = {KEYS[m.group(1).upper()]: float(m.group(2)) for m in READING.finditer(query)}
    st = re.search(r"AQ-\d{2}", query.upper())
    where = st.group(0) if st else "sensor"
    if not ({"pm25", "pm10"} & vals.keys()) or len(vals) < 3:
        return f"INSUFFICIENT DATA at {where}: the AQI needs at least three pollutants, one of them PM2.5 or PM10"
    subs = {p: sub_index(p, c) for p, c in vals.items()}
    worst = max(subs, key=subs.get)
    v = round(subs[worst])
    cat = CATS[next(i for i, (_lo, hi) in enumerate(INDEX) if v <= hi)]
    return (f"AQI {cat.upper()} {v} at {where} (driven by {LABEL[worst]}) · sub-indices: "
            + ", ".join(f"{LABEL[p]} {round(s)}" for p, s in sorted(subs.items(), key=lambda kv: -kv[1])))
