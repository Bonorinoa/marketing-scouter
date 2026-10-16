"""Language gate for X-surface posts: 'capped unless clearly English'. Pure, deterministic, no model calls.

classify(text) -> {lang, clearly_english, reason, en_share, sentences}

Rules (FROZEN 2026-10-13 15:35 PT; constants pinned in tests/test_lang_gate.py):
  1. Strip URLs, at-handles, #hashtags, emoji. If the share of alphabetic chars that are not Latin script
     > NON_LATIN_MAX (0.20) -> capped, reason 'non_latin_script'.
  2. Split into sentences. A sentence with < MIN_ELIGIBLE (4) stopword tokens (any of en/es/pt/fr/it/de)
     is neutral (names, jargon, numbers): never a cap trigger.
  3. Per eligible sentence: en = stopwords only English; oth = stopwords of es/pt/fr/it/de that are not English.
       non-English if oth >= 2 and oth >= en              -> capped 'non_english_sentence' (lang = best other)
       English     if en >= 2 and en >= 2 * oth
       otherwise uncertain                                -> capped 'uncertain_sentence' (lang 'mixed')
  0. (17:05 PT fix) Text is NFKC-normalized and casefolded first (styled Unicode letters count as Latin).
  4. Whole post, over ALL checkable words (17:05 PT fix; constants unchanged):
       other-language stopwords >= MIN_SIGNAL and >= English-only ones -> capped 'non_english_words'
       English-only stopwords < MIN_SIGNAL or < 2x other ones          -> capped 'no_english_signal' (lang 'unknown')
     en_share = English-only / (English-only + other) stopwords over the whole post.
     Very short English posts with < 2 English stopwords ("Great paper!") are still capped.
Known gap: Latin-script languages outside the six lists (Indonesian, Tagalog, Dutch, ...) carry no stopword
signal; they cap only via rule 4 if no English sentence is present, and pass if mixed with clean English.

CLI:  python -m src.lang_gate FILE [--field text]   FILE = .json (list of objects/strings) | .jsonl | .txt (one per line); '-' = stdin.
      Prints one JSON line per item: {id, lang, clearly_english, reason, en_share}.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata

NON_LATIN_MAX = 0.20
MIN_ELIGIBLE = 4
MIN_SIGNAL = 2

STOP = {
    "en": set("""the a an and or but of to in on at by for with from as is are was were be been being have has had do does
did not no this that these those it its they them their there here what which who whom whose when where why how
than then so if because about into over under after before between through during without again more most some any
each other such only own same very can will just should would could may might must i you he she we me him her us our
your my his of all also up out like""".split()),
    "es": set("""el la los las un una unos unas y o pero de del al en por para con sin sobre entre es son era fue ser estar
está están hay que se su sus lo le les como más muy ya también porque cuando donde mi tu nos este esta estos estas ese
esa eso aquí no sí pueden puede igual""".split()),
    "pt": set("""o a os as um uma uns umas e ou mas de do da dos das em no na nos nas por para com sem sobre entre é são era foi
ser estar está estão há que se seu sua seus suas como mais muito já também porque quando onde meu minha não sim pode
podem isso este esta""".split()),
    "fr": set("""le la les un une des et ou mais de du au aux en dans par pour avec sans sur entre est sont était être avoir
il elle ils elles nous vous je tu on que qui ce cette ces son sa ses leur leurs comme plus très déjà aussi parce quand
où ne pas oui peut peuvent""".split()),
    "it": set("""il lo la i gli le un uno una e o ma di del della dei delle in nel nella per con senza su tra fra è sono era
essere avere che chi questo questa questi queste suo sua suoi come più molto già anche perché quando dove non sì può
possono""".split()),
    "de": set("""der die das den dem des ein eine einen einem und oder aber von zu im in auf mit ohne für über zwischen ist
sind war waren sein haben hat ich du er sie es wir ihr nicht auch wie mehr sehr schon weil wenn wo dass kann können
noch nur""".split()),
}
OTHER = ("es", "pt", "fr", "it", "de")
ALL_STOP = set().union(*STOP.values())

_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_TAG = re.compile(r"[@#][\w_]+")
_SENT = re.compile(r"(?:[.!?;:\n¡¿]|\.\.\.|…)+")
_TOK = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.U)


def _clean(text: str) -> str:
    t = _TAG.sub(" ", _URL.sub(" ", text or ""))
    return "".join(ch for ch in t if unicodedata.category(ch) not in ("So", "Sk", "Cs", "Co"))


def non_latin_share(text: str) -> float:
    letters = [ch for ch in _clean(text) if ch.isalpha()]
    if not letters:
        return 0.0
    bad = sum(1 for ch in letters if not unicodedata.name(ch, "").startswith("LATIN"))
    return bad / len(letters)


def _sentence(s: str) -> dict:
    toks = [t.lower().replace("’", "'") for t in _TOK.findall(s)]
    elig = [t for t in toks if t in ALL_STOP]
    en = sum(1 for t in elig if t in STOP["en"] and not any(t in STOP[o] for o in OTHER))
    oth_tokens = [t for t in elig if t not in STOP["en"]]
    per = {o: sum(1 for t in oth_tokens if t in STOP[o]) for o in OTHER}
    oth = len(oth_tokens)
    if len(elig) < MIN_ELIGIBLE:
        verdict, lang = "neutral", None
    elif oth >= MIN_SIGNAL and oth >= en:
        verdict, lang = "other", max(OTHER, key=lambda o: (per[o], -OTHER.index(o)))
    elif en >= MIN_SIGNAL and en >= 2 * oth:
        verdict, lang = "en", "en"
    else:
        verdict, lang = "uncertain", "mixed"
    return {"text": s.strip()[:80], "eligible": len(elig), "en": en, "other": oth, "verdict": verdict, "lang": lang}


def classify(text: str) -> dict:
    # NFKC folds styled Unicode (math bold/italic/monospace letters, fullwidth) to plain letters before the
    # script check and the word checks; casefold for matching.
    text = unicodedata.normalize("NFKC", text or "").casefold()
    nl = non_latin_share(text)
    if nl > NON_LATIN_MAX:
        return {"lang": "non_latin", "clearly_english": False, "reason": "non_latin_script",
                "en_share": 0.0, "non_latin_share": round(nl, 3), "sentences": []}
    cleaned = _clean(text)
    sents = [_sentence(s) for s in _SENT.split(cleaned) if s.strip()]
    # whole-post signal over ALL checkable words (short sentences are neutral only for the per-sentence cap)
    toks = [t.replace("\u2019", "'") for t in _TOK.findall(cleaned)]
    en_tot = sum(1 for t in toks if t in STOP["en"] and not any(t in STOP[o] for o in OTHER))
    oth_toks = [t for t in toks if t in ALL_STOP and t not in STOP["en"]]
    oth_tot = len(oth_toks)
    share = round(en_tot / (en_tot + oth_tot), 3) if (en_tot + oth_tot) else 0.0
    out = {"en_share": share, "en_words": en_tot, "other_words": oth_tot, "non_latin_share": round(nl, 3),
           "sentences": sents}
    en_n = sum(1 for s in sents if s["verdict"] == "en")
    other = [s for s in sents if s["verdict"] == "other"]
    if other:
        langs = [s["lang"] for s in other]
        lang = max(set(langs), key=lambda l: (langs.count(l), -OTHER.index(l)))
        return {**out, "lang": "mixed" if en_n else lang, "detected": lang, "clearly_english": False,
                "reason": "non_english_sentence"}
    if any(s["verdict"] == "uncertain" for s in sents):
        return {**out, "lang": "mixed", "clearly_english": False, "reason": "uncertain_sentence"}
    if oth_tot >= MIN_SIGNAL and oth_tot >= en_tot:          # short sentences, but non-English overall
        per = {o: sum(1 for t in oth_toks if t in STOP[o]) for o in OTHER}
        lang = max(OTHER, key=lambda o: (per[o], -OTHER.index(o)))
        return {**out, "lang": "mixed" if en_tot else lang, "detected": lang, "clearly_english": False,
                "reason": "non_english_words"}
    if not (en_tot >= MIN_SIGNAL and en_tot >= 2 * oth_tot):
        return {**out, "lang": "unknown", "clearly_english": False, "reason": "no_english_signal"}
    return {**out, "lang": "en", "clearly_english": True, "reason": "clearly_english"}


def _items(path: str, field: str):
    raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    if path.endswith(".jsonl"):
        rows = [json.loads(l) for l in raw.splitlines() if l.strip()]
    elif path.endswith(".json") or raw.lstrip()[:1] in "[{":
        rows = json.loads(raw)
        if isinstance(rows, dict):
            rows = rows.get("rows") or rows.get("items") or list(rows.values())
    else:
        rows = [l for l in raw.splitlines() if l.strip()]
    for i, r in enumerate(rows):
        if isinstance(r, str):
            yield i, r
        elif isinstance(r, dict) and isinstance(r.get(field), str):
            yield r.get("id", r.get("post_id", i)), r[field]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Deterministic X language gate (clearly English or capped).")
    ap.add_argument("file")
    ap.add_argument("--field", default="text")
    ap.add_argument("--verbose", action="store_true", help="include per-sentence detail")
    a = ap.parse_args(argv)
    for i, t in _items(a.file, a.field):
        r = classify(t)
        if not a.verbose:
            r = {k: v for k, v in r.items() if k != "sentences"}
        print(json.dumps({"id": i, **r}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
