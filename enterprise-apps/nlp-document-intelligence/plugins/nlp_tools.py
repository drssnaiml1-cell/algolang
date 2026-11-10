"""AlgoNLP Document Intelligence™ tools: classical, inspectable NLP on a 3,000-message bank corpus.

    nlp.classify    multinomial Naive Bayes (unigrams + bigrams, Laplace smoothing) trained on weeks 1-9,
                    reported with held-out macro-F1 on weeks 10-12; classifies one message with its probability
    nlp.entities    named entities: money amounts, dates, card endings, branches/places, banks, channels (UPI,
                    OTP, ATM, PIN)
    nlp.summarize   extractive summary with TextRank (sentence graph, PageRank by power iteration)
    nlp.trends      corpus analytics: weekly volume per category and emerging topics (latest two weeks vs
                    the eight before), with the most distinctive words per category (log-odds)

All messages are synthetic (data/messages.csv). Personal data in a message is masked by the program's
`redact pii` policy before any language model sees it; these tools run inside the organisation.
"""
from __future__ import annotations

import csv
import math
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from algoruntime import register_tool

DATA = Path(__file__).resolve().parent.parent / "data"
STOP = set("a an the to of and or for my me i is in on at it be this that was with from have has can your you "
           "please kindly how do what are am not no but as by".split())
LABELS = {"card_block": "card block", "loan_query": "loan query", "fraud_report": "FRAUD REPORT",
          "kyc_update": "KYC update", "statement": "statement request", "service_complaint": "service complaint"}


@lru_cache(maxsize=1)
def corpus():
    with open(DATA / "messages.csv", encoding="utf-8") as f:
        return [(r["id"], int(r["week"]), r["label"], r["text"]) for r in csv.DictReader(f)]


def tokens(text):
    words = [w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOP and len(w) > 1]
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]


@lru_cache(maxsize=1)
def naive_bayes():
    train = [(lab, tokens(t)) for _i, wk, lab, t in corpus() if wk <= 9]
    prior, counts, total = Counter(), defaultdict(Counter), Counter()
    for lab, toks in train:
        prior[lab] += 1
        counts[lab].update(toks)
        total[lab] += len(toks)
    vocab = set().union(*counts.values())
    return prior, counts, total, vocab, len(train)


def predict(text):
    prior, counts, total, vocab, n = naive_bayes()
    toks = tokens(text)
    scores = {}
    for lab in prior:
        s = math.log(prior[lab] / n)
        for t in toks:
            s += math.log((counts[lab][t] + 1) / (total[lab] + len(vocab)))
        scores[lab] = s
    m = max(scores.values())
    z = sum(math.exp(v - m) for v in scores.values())
    probs = {k: math.exp(v - m) / z for k, v in scores.items()}
    best = max(probs, key=probs.get)
    return best, probs


@lru_cache(maxsize=1)
def held_out():
    test = [(lab, t) for _i, wk, lab, t in corpus() if wk >= 10]
    tp, fp, fn = Counter(), Counter(), Counter()
    for lab, t in test:
        p, _ = predict(t)
        if p == lab:
            tp[lab] += 1
        else:
            fp[p] += 1
            fn[lab] += 1
    f1 = {}
    for lab in LABELS:
        prec = tp[lab] / (tp[lab] + fp[lab]) if tp[lab] + fp[lab] else 0
        rec = tp[lab] / (tp[lab] + fn[lab]) if tp[lab] + fn[lab] else 0
        f1[lab] = 2 * prec * rec / (prec + rec) if prec + rec else 0
    return sum(f1.values()) / len(f1), sum(tp.values()) / len(test), len(test)


def message_of(query):
    """The message text is everything after the first colon or quote, or the whole query."""
    m = re.search(r"message[:\s]+(.*)", query, re.I | re.S)
    return (m.group(1) if m else query).strip()


@register_tool("nlp.classify", "Classify a customer message with Naive Bayes (held-out macro-F1 reported)")
def nlp_classify(query: str) -> str:
    text = message_of(query)
    lab, probs = predict(text)
    f1, acc, n = held_out()
    second = sorted(probs.items(), key=lambda kv: -kv[1])[1]
    return (f"CATEGORY {LABELS[lab]} (probability {probs[lab]:.3f}; next {LABELS[second[0]]} {second[1]:.3f})\n"
            f"model: multinomial Naive Bayes, unigrams + bigrams, trained on weeks 1-9 · held-out weeks 10-12: "
            f"macro-F1 {f1:.3f}, accuracy {acc:.1%} on {n:,} messages")


MONEY = re.compile(r"(?:Rs\.?|INR|₹)\s?[\d,]+(?:\.\d+)?", re.I)
DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b(?:today|yesterday|tomorrow)\b", re.I)
CARD = re.compile(r"\bending\s+(\d{4})\b", re.I)
PLACES = ["Ameerpet", "Koramangala", "Andheri", "Salt Lake", "T Nagar", "Hazratganj", "Gachibowli", "Kothrud"]
BANKS = ["Deccan Bank", "Konark Bank", "Sahyadri Bank"]
CHANNELS = ["UPI", "OTP", "ATM", "PIN", "app", "branch", "customer care"]


@register_tool("nlp.entities", "Named entities in a message: amounts, dates, card endings, places, banks, channels")
def nlp_entities(query: str) -> str:
    text = message_of(query)
    ents = [("MONEY", m.group(0)) for m in MONEY.finditer(text)] + [("DATE", m.group(0)) for m in DATE.finditer(text)]
    ents += [("CARD_ENDING", m.group(1)) for m in CARD.finditer(text)]
    ents += [("PLACE", p) for p in PLACES if p.lower() in text.lower()]
    ents += [("BANK", b) for b in BANKS if b.lower() in text.lower()]
    ents += [("CHANNEL", c) for c in CHANNELS if re.search(rf"\b{re.escape(c)}\b", text, re.I)]
    if not ents:
        return "ENTITIES none found"
    return "ENTITIES " + " · ".join(f"{k}: {v}" for k, v in ents)


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


@register_tool("nlp.summarize", "Extractive TextRank summary of a message or document")
def nlp_summarize(query: str) -> str:
    text = message_of(query)
    sents = sentences(text)
    if len(sents) <= 1:
        return f"SUMMARY {text}"
    bags = [set(w for w in re.findall(r"[a-z]+", s.lower()) if w not in STOP) for s in sents]
    n = len(sents)
    W = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j and bags[i] and bags[j]:
                W[i][j] = len(bags[i] & bags[j]) / (math.log(len(bags[i]) + 1) + math.log(len(bags[j]) + 1))
    rank = [1 / n] * n
    for _ in range(50):                                    # PageRank, damping 0.85
        rank = [0.15 / n + 0.85 * sum(W[j][i] / (sum(W[j]) or 1) * rank[j] for j in range(n)) for i in range(n)]
    keep = sorted(sorted(range(n), key=lambda i: -rank[i])[:max(1, n // 2)])
    return "SUMMARY " + " ".join(sents[i] for i in keep) + f"  ({len(keep)} of {n} sentences, TextRank)"


@register_tool("nlp.trends", "Corpus analytics: weekly volume per category, emerging topics, distinctive words")
def nlp_trends(query: str) -> str:
    docs = corpus()
    weeks = sorted({wk for _i, wk, _l, _t in docs})
    last, prev = weeks[-2:], weeks[-10:-2]
    vol = defaultdict(Counter)
    for _i, wk, lab, _t in docs:
        vol[lab][wk] += 1
    words = defaultdict(Counter)
    for _i, _wk, lab, t in docs:
        words[lab].update(w for w in tokens(t) if "_" not in w)
    allw = sum(words.values(), Counter())
    lines, rising = [], []
    for lab in LABELS:
        recent = sum(vol[lab][w] for w in last) / len(last)
        before = sum(vol[lab][w] for w in prev) / len(prev)
        growth = recent / before - 1 if before else 0
        if growth > 0.5:
            rising.append(f"{LABELS[lab]} (+{growth:.0%})")
        n_l, n_all = sum(words[lab].values()), sum(allw.values())
        score = {w: math.log((c + 1) / (n_l + 1)) - math.log((allw[w] - c + 1) / (n_all - n_l + 1))
                 for w, c in words[lab].items() if c >= 5}
        top = ", ".join(w for w, _ in sorted(score.items(), key=lambda kv: -kv[1])[:4])
        lines.append(f"  {LABELS[lab]:<18} {before:6.1f}/week → {recent:6.1f}/week ({growth:+.0%})  words: {top}")
    head = ("EMERGING " + ", ".join(rising) + f" in weeks {last[0]}-{last[-1]}") if rising else "NO EMERGING TOPIC"
    return head + f"\n{len(docs):,} messages over {len(weeks)} weeks\n" + "\n".join(lines)
