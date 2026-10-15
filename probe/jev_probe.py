"""Jev probe: fetch real headlines, ask Jev 4 questions each, print results + cost.

Stdlib only. The key is read from ~/.hermes/.env (TYPESAFE_API_KEY) and never printed.

  python3 jev_probe.py fetch            # pull RSS items -> items.json
  python3 jev_probe.py run [gloss]      # Jev on items.json (or English glosses) -> results[_gloss].json
  python3 jev_probe.py compare          # Spanish original vs English gloss agreement
"""
import json, os, re, sys, time, ssl, urllib.request, xml.etree.ElementTree as ET
from html import unescape

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"           # pinned, not the alias, so results are comparable
FEEDS = {
    "la_nacion": ("https://www.lanacion.com.ar/arc/outboundfeeds/rss/?outputType=xml", "es"),
    "la_gaceta": ("https://www.lagaceta.com.ar/rss/", "es"),
    "la_times_opinion": ("https://www.latimes.com/opinion/rss2.0.xml", "en"),
}
N_PER_FEED = 12


def get_key():
    for line in open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8"):
        if line.startswith("TYPESAFE_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    sys.exit("TYPESAFE_API_KEY not found in ~/.hermes/.env")


def http(url, data=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers=headers or {"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(s or ""))).strip()


def fetch():
    items = []
    for name, (url, lang) in FEEDS.items():
        status, text = http(url)
        # stdlib ET does not fetch external entities; feeds are 3 trusted outlets. Use defusedxml if sources widen.
        root = ET.fromstring(text.encode("utf-8"))
        n = 0
        for it in root.iter("item"):
            title = clean(it.findtext("title"))
            desc = clean(it.findtext("description"))[:500]
            if not title:
                continue
            items.append({"id": "%s_%02d" % (name, n), "source": name, "lang": lang,
                          "title": title, "summary": desc, "link": it.findtext("link")})
            n += 1
            if n >= N_PER_FEED:
                break
    json.dump(items, open(os.path.join(HERE, "items.json"), "w"), ensure_ascii=False, indent=1)
    for i in items:
        print(i["id"], "|", i["title"][:100])
    print(len(items), "items")


def questions(interests):
    criteria = {i["name"]: i["description"] for i in interests}
    return {
        "lens": {"type": "choice",
                 "instructions": ("Of this person's interests, which is the most useful lens through "
                                  "which they could write about this item? Name the best one."),
                 "criteria": criteria},
        "lens_supported": {"type": "noul",
                 "instructions": ("Is there at least one listed interest whose connection to this item is "
                                  "substantive (shared argument, mechanism, method or evidence), not merely "
                                  "the same broad subject or shared vocabulary?")},
        "opportunity": {"type": "score",
                 "instructions": ("How good an opportunity is this item for the person to publish a "
                                  "substantive, expert op-ed, letter or comment of their own?"),
                 "criteria": ["none: unrelated or nothing to add", "thin: tangential",
                              "usable: relevant, could add a perspective",
                              "strong: squarely in their expertise with a clear angle",
                              "exceptional: timely and uniquely suited"]},
        "needs_personal": {"type": "noul",
                 "instructions": ("Would a credible response to this item require the author to disclose "
                                  "private personal details (family, health, location, immigration, finances)?")},
    }


def call(key, state, qs):
    body = json.dumps({"model": MODEL, "state": state, "questions": qs}, ensure_ascii=False).encode()
    t = time.monotonic()
    status, text = http(ENDPOINT, body, {"Authorization": "Bearer " + key, "Content-Type": "application/json",
                                         "Accept": "application/json", "User-Agent": "marketing-scouter/probe"})
    ms = int((time.monotonic() - t) * 1000)
    if status != 200:
        # never echo headers; body is safe
        raise SystemExit("HTTP %s: %s" % (status, text[:300]))
    return json.loads(text), ms


def run(gloss=False):
    key = get_key()
    interests = json.load(open(os.path.join(ROOT, "interests.json")))
    qs = questions(interests)
    items = json.load(open(os.path.join(HERE, "items.json")))
    gl = {}
    if gloss:
        gl = json.load(open(os.path.join(HERE, "gloss.json")))
    out, tot_in, first = [], 0, True
    for it in items:
        if gloss:
            if it["id"] not in gl:
                continue
            state = {"title": gl[it["id"]]["title"], "summary": gl[it["id"]]["summary"]}
        else:
            state = {"title": it["title"], "summary": it["summary"]}
        resp, ms = call(key, state, qs)
        if first:
            print("RAW SHAPE (first response):", json.dumps(resp, ensure_ascii=False)[:900], "\n")
            first = False
        a = resp["answers"]
        usage = resp.get("usage", {})
        tot_in += usage.get("input_tokens", 0)
        row = {"id": it["id"], "lang": it["lang"], "title": it["title"][:90],
               "lens": a["lens"].get("choice"), "lens_conf": a["lens"].get("confidence"),
               "supported": a["lens_supported"].get("noul"),
               "opp": a["opportunity"].get("score"), "opp_conf": a["opportunity"].get("confidence"),
               "personal": a["needs_personal"].get("noul"), "ms": ms, "in_tok": usage.get("input_tokens")}
        out.append(row)
        print("%-18s opp=%.2f sup=%.2f pers=%.2f %4dms | %s | %s" % (
            row["id"], row["opp"] or -1, row["supported"] or -1, row["personal"] or -1, ms,
            (row["lens"] or "")[:34], row["title"][:60]))
    json.dump(out, open(os.path.join(HERE, "results_gloss.json" if gloss else "results.json"), "w"),
              ensure_ascii=False, indent=1)
    print("\n%d calls, %d input tokens, est cost $%.6f" % (len(out), tot_in, tot_in * 0.042 / 1e6))


def run_v2():
    """v2: one atomic noul per interest ('is this item substantively about X?'); relevance = max.
    Replaces the compound 'opportunity' score, which returned ~2.0-2.4 for everything."""
    key = get_key()
    interests = json.load(open(os.path.join(ROOT, "interests.json")))
    qs = {"i%d" % n: {"type": "noul",
                      "instructions": "Is this item substantively about: %s. %s (Reply high only if the item itself "
                                      "is about this, not merely adjacent or sharing a few words.)"
                                      % (i["name"], i["description"])}
          for n, i in enumerate(interests)}
    items = json.load(open(os.path.join(HERE, "items.json")))
    out, tot = [], 0
    for it in items:
        resp, ms = call(key, {"title": it["title"], "summary": it["summary"]}, qs)
        ps = {interests[int(k[1:])]["name"]: v.get("noul") for k, v in resp["answers"].items()}
        best = max(ps, key=ps.get)
        tot += resp.get("usage", {}).get("input_tokens", 0)
        out.append({"id": it["id"], "title": it["title"][:80], "best": best, "p": ps[best], "all": ps})
    out.sort(key=lambda r: -r["p"])
    json.dump(out, open(os.path.join(HERE, "results_v2.json"), "w"), ensure_ascii=False, indent=1)
    for r in out:
        print("%.2f  %-18s %-36s | %s" % (r["p"], r["id"], r["best"][:36], r["title"][:55]))
    print("\n%d calls, %d input tokens, est cost $%.6f" % (len(out), tot, tot * 0.042 / 1e6))


def compare():
    a = {r["id"]: r for r in json.load(open(os.path.join(HERE, "results.json")))}
    b = {r["id"]: r for r in json.load(open(os.path.join(HERE, "results_gloss.json")))}
    same, dopp, n = 0, [], 0
    for k in b:
        if k not in a:
            continue
        n += 1
        same += a[k]["lens"] == b[k]["lens"]
        dopp.append(abs((a[k]["opp"] or 0) - (b[k]["opp"] or 0)))
        print("%-18s lens %s | opp %.2f vs %.2f | sup %.2f vs %.2f" % (
            k, "SAME" if a[k]["lens"] == b[k]["lens"] else "DIFF", a[k]["opp"], b[k]["opp"],
            a[k]["supported"], b[k]["supported"]))
    print("\nlens agreement %d/%d, mean |opp diff| %.2f" % (same, n, sum(dopp) / max(n, 1)))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    {"fetch": fetch, "run": lambda: run("gloss" in sys.argv[2:]), "v2": run_v2, "compare": compare}[cmd]()
