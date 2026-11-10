"""AlgoBharat Bhasha Desk™ tools: Indian-language AI for citizen services, deterministic and inspectable.

    lang.detect        language from Unicode script (Devanagari, Bengali, Gurmukhi, Gujarati, Odia, Tamil, Telugu,
                       Kannada, Malayalam, Urdu/Arabic, Latin); Hindi vs Marathi by marker words; English vs
                       Hindi written in Latin letters (Hinglish) by common romanised words; mixed-script flag
    lang.transliterate any Brahmic script to Latin (ISO 15919 style): inherent vowel, vowel signs, virama,
                       anusvara; Hindi word-final schwa deletion
    lang.intent        the citizen's need (pension, ration card, electricity, water, scholarship, land records)
                       from a multilingual lexicon (data/lexicon.json)
    lang.reply         an approved acknowledgement template in the citizen's language (data/replies.json)
    lang.coverage      accuracy of detection and intent on a 4,800-query multilingual test set, including
                       code-mixed queries (an Indic sentence with English words)

The reply templates are written for this example; have native speakers review templates before real use.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from algoruntime import register_tool

DATA = Path(__file__).resolve().parent.parent / "data"

SCRIPTS = [  # (start, end, script, default language code, language name)
    (0x0900, 0x097F, "Devanagari", "hi", "Hindi"), (0x0980, 0x09FF, "Bengali", "bn", "Bengali"),
    (0x0A00, 0x0A7F, "Gurmukhi", "pa", "Punjabi"), (0x0A80, 0x0AFF, "Gujarati", "gu", "Gujarati"),
    (0x0B00, 0x0B7F, "Odia", "or", "Odia"), (0x0B80, 0x0BFF, "Tamil", "ta", "Tamil"),
    (0x0C00, 0x0C7F, "Telugu", "te", "Telugu"), (0x0C80, 0x0CFF, "Kannada", "kn", "Kannada"),
    (0x0D00, 0x0D7F, "Malayalam", "ml", "Malayalam"), (0x0600, 0x06FF, "Arabic", "ur", "Urdu"),
]
NAMES = {"hi": "Hindi", "mr": "Marathi", "bn": "Bengali", "pa": "Punjabi", "gu": "Gujarati", "or": "Odia",
         "ta": "Tamil", "te": "Telugu", "kn": "Kannada", "ml": "Malayalam", "ur": "Urdu", "en": "English",
         "hi-Latn": "Hindi in Latin letters"}
MARATHI = {"आहे", "आहेत", "नाही", "माझा", "माझी", "माझे", "आणि", "करा", "झाली", "झाला", "दिसत", "आम्हाला", "गावात", "उतारा"}
HINDI = {"है", "हैं", "नहीं", "मेरा", "मेरी", "और", "करें", "रहा", "रही", "हमारे", "गाँव", "क्या"}
HINGLISH = {"hai", "nahi", "nahin", "kya", "mera", "meri", "mujhe", "kab", "kaise", "abhi", "tak", "karun", "aur",
            "hamara", "hamare", "gaon", "paisa", "bana", "aaya", "raha", "rahi", "kripya", "madad", "ka", "ki", "ke"}


def body(query):
    m = re.search(r"(?:query|message)[:\s]+(.*)", query, re.I | re.S)
    return (m.group(1) if m else query).strip()


def detect(text):
    counts, latin = {}, 0
    for ch in text:
        cp = ord(ch)
        if ch.isalpha() and cp < 0x250:
            latin += 1
            continue
        for a, b, script, code, _n in SCRIPTS:
            if a <= cp <= b and unicodedata.category(ch)[0] in "LM":
                counts[(script, code)] = counts.get((script, code), 0) + 1
    total = sum(counts.values()) + latin
    if not total:
        return None, 0.0, {}
    if counts:
        (script, code), n = max(counts.items(), key=lambda kv: kv[1])
    else:
        script, code, n = "Latin", "en", latin
    words = set(re.findall(r"[\wऀ-ൿ]+", text.lower()))
    if script == "Devanagari":
        code = "mr" if len(words & MARATHI) > len(words & HINDI) else "hi"
    if script == "Latin":
        code = "hi-Latn" if len(words & HINGLISH) >= 2 else "en"
    if n < latin and counts:                     # more Latin letters than the Indic script: still mixed
        pass
    mixed = len([k for k, v in counts.items() if v > 2]) + (1 if latin > 3 and counts else 0) > 1
    return code, n / total, dict(script=script, mixed=mixed, latin=latin)


@register_tool("lang.detect", "Detect the Indian language of a citizen's query from its script and words")
def lang_detect(query: str) -> str:
    text = body(query)
    code, share, info = detect(text)
    if code is None:
        return "LANGUAGE unknown (no letters)"
    return (f"LANGUAGE {NAMES[code]} ({code}) · {info['script']} script, {share:.0%} of letters"
            + (" · code-mixed with Latin/English words" if info["mixed"] else ""))


# ───────────────────────────── transliteration ─────────────────────────────
VOWELS = {0x0D: "ê", 0x11: "ô", 0x05: "a", 0x06: "ā", 0x07: "i", 0x08: "ī", 0x09: "u", 0x0A: "ū", 0x0B: "r̥", 0x0C: "l̥", 0x0E: "e",
          0x0F: "e", 0x10: "ai", 0x12: "o", 0x13: "o", 0x14: "au"}
SIGNS = {0x45: "ê", 0x49: "ô", 0x3E: "ā", 0x3F: "i", 0x40: "ī", 0x41: "u", 0x42: "ū", 0x43: "r̥", 0x46: "e", 0x47: "e", 0x48: "ai",
         0x4A: "o", 0x4B: "o", 0x4C: "au", 0x57: "au"}
CONS = {0x15: "k", 0x16: "kh", 0x17: "g", 0x18: "gh", 0x19: "ṅ", 0x1A: "c", 0x1B: "ch", 0x1C: "j", 0x1D: "jh",
        0x1E: "ñ", 0x1F: "ṭ", 0x20: "ṭh", 0x21: "ḍ", 0x22: "ḍh", 0x23: "ṇ", 0x24: "t", 0x25: "th", 0x26: "d",
        0x27: "dh", 0x28: "n", 0x29: "ṉ", 0x2A: "p", 0x2B: "ph", 0x2C: "b", 0x2D: "bh", 0x2E: "m", 0x2F: "y",
        0x30: "r", 0x31: "ṟ", 0x32: "l", 0x33: "ḷ", 0x34: "ḻ", 0x35: "v", 0x36: "ś", 0x37: "ṣ", 0x38: "s", 0x39: "h"}
MARKS = {0x01: "m̐", 0x02: "ṁ", 0x03: "ḥ"}
DRAVIDIAN = {"Tamil", "Telugu", "Kannada", "Malayalam"}


def transliterate(text):
    out, words = [], re.split(r"(\s+)", text)
    for w in words:
        res, i, base, script = [], 0, None, None
        chars = list(w)
        while i < len(chars):
            cp = ord(chars[i])
            blk = next(((a, s) for a, b, s, _c, _n in SCRIPTS[:-1] if a <= cp <= b), None)
            if blk is None:
                res.append(chars[i])
                i += 1
                continue
            base, script = blk
            off = cp - base
            long_eo = script in DRAVIDIAN
            if off in CONS:
                c = CONS[off]
                nxt = ord(chars[i + 1]) - base if i + 1 < len(chars) else None
                if nxt == 0x3C and i + 2 < len(chars):               # nukta (क़ → q): keep the base sound
                    i += 1
                    nxt = ord(chars[i + 1]) - base if i + 1 < len(chars) else None
                if nxt == 0x4D:
                    res.append(c)
                    i += 2
                    continue
                if nxt in SIGNS:
                    v = SIGNS[nxt]
                    v = {"e": "ē", "o": "ō"}.get(v, v) if long_eo and nxt in (0x47, 0x4B) else v
                    res.append(c + v)
                    i += 2
                    continue
                res.append(c + "a")
            elif off in VOWELS:
                v = VOWELS[off]
                res.append({"e": "ē", "o": "ō"}.get(v, v) if long_eo and off in (0x0F, 0x13) else v)
            elif off in MARKS:
                res.append(MARKS[off])
            elif 0x66 <= off <= 0x6F:
                res.append(str(off - 0x66))
            elif off in (0x64, 0x65):
                res.append(".")
            i += 1
        s = "".join(res)
        if script == "Devanagari" and len(s) > 2 and s.endswith("a") and not s.endswith("aa"):
            s = s[:-1]                                                 # Hindi drops the final inherent vowel
        out.append(s)
    return "".join(out)


@register_tool("lang.transliterate", "Transliterate Indian-script text to Latin letters (ISO 15919 style)")
def lang_transliterate(query: str) -> str:
    text = body(query)
    return f"LATIN {transliterate(text)}"


# ───────────────────────────── intent and replies ─────────────────────────────
@lru_cache(maxsize=1)
def lexicon():
    return json.loads((DATA / "lexicon.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def replies():
    return json.loads((DATA / "replies.json").read_text(encoding="utf-8"))


def intent_of(text):
    low = text.lower()
    hits = {}
    for intent, by_lang in lexicon().items():
        for lang, words in by_lang.items():
            for w in words:
                found = re.search(rf"\b{re.escape(w)}\b", low) if w.isascii() else (w in text)
                if found and w not in hits.get(intent, []):
                    hits.setdefault(intent, []).append(w)
    if not hits:
        return None, []
    best = max(hits, key=lambda k: len(hits[k]))
    return best, hits[best]


@register_tool("lang.intent", "What the citizen needs: pension, ration card, electricity, water, scholarship, land records")
def lang_intent(query: str) -> str:
    text = body(query)
    intent, words = intent_of(text)
    if intent is None:
        return "UNKNOWN INTENT: no service keyword in any supported language; a person should read it"
    return f"INTENT {intent} (matched: {', '.join(words)})"


@register_tool("lang.reply", "Approved acknowledgement in the citizen's own language")
def lang_reply(query: str) -> str:
    text = body(query)
    code, _s, _i = detect(text)
    intent, _ = intent_of(text)
    if intent is None:
        return "NO TEMPLATE: unknown intent"
    lang = code if code in replies()["template"] else "en"
    ref = "BH-" + hashlib.sha256(text.encode()).hexdigest()[:6].upper()
    msg = replies()["template"][lang].format(service=replies()["service"][intent][lang], ref=ref)
    note = "" if lang == code else f" (no approved {NAMES.get(code, code)} template yet: English used)"
    return f"REPLY [{NAMES[lang]}]{note} {msg}"


# ───────────────────────────── large-scale coverage test ─────────────────────────────
FRAMES = {
    "hi": ["मेरी {kw} की समस्या है, कृपया मदद करें", "{kw} के बारे में जानकारी चाहिए", "हमारे गाँव में {kw} की शिकायत है"],
    "mr": ["माझी {kw} संबंधी तक्रार आहे", "{kw} बद्दल माहिती हवी आहे", "आमच्या गावात {kw} ची अडचण आहे"],
    "te": ["నా {kw} సమస్య ఉంది, దయచేసి సహాయం చేయండి", "{kw} గురించి సమాచారం కావాలి", "మా ఊరిలో {kw} ఫిర్యాదు ఉంది"],
    "ta": ["என் {kw} பிரச்சினை உள்ளது, உதவுங்கள்", "{kw} பற்றி தகவல் வேண்டும்", "எங்கள் ஊரில் {kw} புகார் உள்ளது"],
    "bn": ["আমার {kw} নিয়ে সমস্যা আছে, সাহায্য করুন", "{kw} সম্পর্কে জানতে চাই", "আমাদের গ্রামে {kw} নিয়ে অভিযোগ আছে"],
    "kn": ["ನನ್ನ {kw} ಸಮಸ್ಯೆ ಇದೆ, ದಯವಿಟ್ಟು ಸಹಾಯ ಮಾಡಿ", "{kw} ಬಗ್ಗೆ ಮಾಹಿತಿ ಬೇಕು", "ನಮ್ಮ ಊರಿನಲ್ಲಿ {kw} ದೂರು ಇದೆ"],
    "gu": ["મારી {kw} ની સમસ્યા છે, કૃપા કરીને મદદ કરો", "{kw} વિશે માહિતી જોઈએ છે"],
    "en": ["I have a problem with my {kw}, please help", "I need information about {kw}"],
    "hi-Latn": ["mera {kw} ka kaam abhi tak nahi hua", "{kw} ke baare mein madad chahiye, kya karun"],
}


# Phrasings the lexicon does not contain (variant spellings, synonyms): honest misses for the coverage test.
UNSEEN = {"hi": {"pension": "बुढ़ापे का भत्ता", "electricity_bill": "लाइट का बिल", "water_supply": "नल"},
          "te": {"electricity_bill": "కరెంట్ బిల్", "pension": "వృద్ధాప్య భృతి"},
          "ta": {"electricity_bill": "கரண்ட் பில்", "scholarship": "ஸ்காலர்ஷிப்"},
          "mr": {"electricity_bill": "लाईट बिल"}, "kn": {"water_supply": "ಕುಡಿಯುವ ನೀರ"},
          "en": {"electricity_bill": "power outage", "land_records": "property papers"},
          "hi-Latn": {"pension": "budhapa bhatta", "water_supply": "nal"}}
GREETINGS = {"hi": "नमस्ते, आप कैसे हैं?", "te": "నమస్కారం, మీరు ఎలా ఉన్నారు?", "ta": "வணக்கம், எப்படி இருக்கிறீர்கள்?",
             "mr": "नमस्कार, तुम्ही कसे आहात?", "bn": "নমস্কার, আপনি কেমন আছেন?", "kn": "ನಮಸ್ಕಾರ, ಹೇಗಿದ್ದೀರಿ?",
             "gu": "નમસ્તે, તમે કેમ છો?", "en": "Hello, good morning to the team", "hi-Latn": "namaste, aap kaise hai"}


@lru_cache(maxsize=1)
def coverage():
    rng = random.Random(41)
    lex = lexicon()
    rows = []
    for _ in range(4800):
        lang = rng.choice(list(FRAMES))
        u = rng.random()
        if u < 0.06:                                   # no service request at all: the right answer is "unknown"
            rows.append((lang, None, GREETINGS[lang]))
            continue
        intent = rng.choice(list(lex))
        kw = rng.choice(lex[intent][lang])
        if u < 0.16 and intent in UNSEEN.get(lang, {}):
            kw = UNSEEN[lang][intent]                  # a phrasing the lexicon has never seen
        text = rng.choice(FRAMES[lang]).format(kw=kw)
        if lang not in ("en", "hi-Latn") and rng.random() < 0.15:
            text += " " + rng.choice(["please", "urgent", "office", "online form", "sir"])     # code-mixing
        rows.append((lang, intent, text))
    lang_ok = intent_ok = 0
    per = {}
    for lang, intent, text in rows:
        code, _s, _i = detect(text)
        it, _ = intent_of(text)
        lang_ok += code == lang
        intent_ok += it == intent
        a, b = per.get(lang, (0, 0))
        per[lang] = (a + (code == lang and it == intent), b + 1)
    return len(rows), lang_ok / len(rows), intent_ok / len(rows), per


@register_tool("lang.coverage", "Accuracy of language and intent detection on a 4,800-query multilingual test set")
def lang_coverage(query: str) -> str:
    n, la, ia, per = coverage()
    worst = min(per.items(), key=lambda kv: kv[1][0] / kv[1][1])
    return (f"COVERAGE {n:,} queries in {len(per)} languages (incl. greetings and unseen phrasings): "
            f"language {la:.1%} · intent {ia:.1%} · "
            f"weakest {NAMES[worst[0]]} {worst[1][0] / worst[1][1]:.1%}\n"
            + " · ".join(f"{NAMES[k]} {a / b:.0%}" for k, (a, b) in sorted(per.items())))
