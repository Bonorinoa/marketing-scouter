"""Manual capture of one item the user found themselves (the X / LinkedIn paste-a-URL path).

One URL = one explicit action. X posts are read through X's public oEmbed endpoint (no API key, no
timeline access). Anything else (LinkedIn etc.) needs the text pasted with --text: no scraping.
Experimental X *discovery* (xAI x_search) is deliberately not wired in until credits are available.
"""
import json
import re
import urllib.parse

from . import config, jev, sources, store

X_URL = re.compile(r"^https?://(?:www\.)?(?:x|twitter)\.com/([^/]+)/status/(\d+)")


def read_x_post(url):
    api = "https://publish.x.com/oembed?omit_script=true&url=" + urllib.parse.quote(url, safe="")
    status, text = config.http_get(api)
    if status != 200:
        raise RuntimeError("X oEmbed returned HTTP %d (post deleted or private?)" % status)
    obj = json.loads(text)
    return obj.get("author_name", ""), config.clean_text(obj.get("html", ""), 1000)


def capture(url, text=None, panel="commentary"):
    m = X_URL.match(url)
    if text:
        author, body = (m.group(1) if m else ""), config.clean_text(text, 1000)
    elif m:
        author, body = read_x_post(url)
    else:
        raise SystemExit("only X post URLs can be read automatically; pass the text with --text")
    title = (("%s: " % author) if author else "") + body[:140]
    item = {"panel": panel, "source": "manual_x" if m else "manual", "title": title, "url": url,
            "summary": body, "published": "", "meta": {"lang": None, "captured": True}}
    db = store.connect()
    new = store.upsert_candidates(db, [item])
    cid = sources.candidate_id(url)
    key = config.env_value("TYPESAFE_API_KEY")
    if key:
        store.save_score(db, cid, config.interests_version(), jev.score_item(key, item, config.interests()))
    store.log(db, "capture", id=cid, new=bool(new))
    return store.get_candidate(db, cid)
