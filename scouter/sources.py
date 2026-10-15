"""Source fetchers. Each returns a list of candidate dicts:
   panel, source, title, url, summary, published, meta.
Read-only GETs on public feeds/APIs. Reddit goes through RSS (the .json endpoint returns 403).
"""
import hashlib
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

from . import config


def candidate_id(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child_text(el, *names):
    for ch in el:
        if _local(ch.tag) in names and (ch.text or "").strip():
            return ch.text
    return ""


def _atom_link(el):
    for ch in el:
        if _local(ch.tag) == "link":
            return ch.attrib.get("href") or (ch.text or "").strip()
    return ""


def fetch_rss(src):
    """RSS 2.0 (item) and Atom (entry), namespace-agnostic."""
    status, text = config.http_get(src["url"])
    if status != 200:
        raise OSError("%s: HTTP %d" % (src["id"], status))
    # stdlib ElementTree does not fetch external entities; sources are a fixed, trusted list.
    root = ET.fromstring(text.encode("utf-8"))
    out = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        title = config.clean_text(_child_text(el, "title"))
        url = _atom_link(el) or config.clean_text(_child_text(el, "link"))
        if not title or not url:
            continue
        summary = config.clean_text(_child_text(el, "description", "summary", "content", "encoded"), 600)
        published = _child_text(el, "pubDate", "published", "updated", "date")
        out.append({"panel": src["panel"], "source": src["id"], "title": title, "url": url,
                    "summary": summary, "published": published.strip(), "meta": {"lang": src.get("lang")}})
        if len(out) >= src.get("limit", 25):
            break
    return out


def fetch_reddit_rss(src):
    """Unauthenticated Reddit RSS rate-limits hard (HTTP 429 after ~1 request/second): space calls out
    and retry once after a pause. A source that still fails is reported and skipped by the scout."""
    time.sleep(3.0)
    src = dict(src, url="https://www.reddit.com/r/%s/top/.rss?t=day" % src["sub"])
    try:
        items = fetch_rss(src)
    except OSError as e:
        if "429" not in str(e):
            raise
        time.sleep(8.0)
        items = fetch_rss(src)
    for it in items:
        it["meta"]["subreddit"] = src["sub"]
    return items


def _hn_item(hit, src):
    obj = hit["objectID"]
    return {"panel": src["panel"], "source": src["id"], "title": hit.get("title") or "",
            "url": "https://news.ycombinator.com/item?id=%s" % obj,
            "summary": config.clean_text(hit.get("story_text") or "", 600),
            "published": hit.get("created_at") or "",
            "meta": {"points": hit.get("points"), "comments": hit.get("num_comments"),
                     "external_url": hit.get("url"), "lang": "en"}}


def _hn_get(params):
    url = "https://hn.algolia.com/api/v1/search_by_date?" + urllib.parse.urlencode(params)
    status, text = config.http_get(url)
    if status != 200:
        raise OSError("hn: HTTP %d" % status)
    return json.loads(text).get("hits", [])


def fetch_hn_search(src):
    """Keyword stories from the last N days with a points floor: a rough 'persistent discussion' signal."""
    cutoff = int(time.time()) - src.get("days", 14) * 86400
    seen, out = set(), []
    for q in src["queries"]:
        hits = _hn_get({"query": q, "tags": "story", "hitsPerPage": src.get("per_query", 15),
                        "numericFilters": "created_at_i>%d,points>=%d" % (cutoff, src.get("min_points", 15))})
        for h in hits:
            if h["objectID"] in seen or not h.get("title"):
                continue
            seen.add(h["objectID"])
            item = _hn_item(h, src)
            item["meta"]["query"] = q
            out.append(item)
    return out


def fetch_hn_front(src):
    hits = _hn_get({"tags": "front_page", "hitsPerPage": src.get("limit", 30)})
    return [_hn_item(h, src) for h in hits if h.get("title")]


FETCHERS = {"rss": fetch_rss, "reddit_rss": fetch_reddit_rss,
            "hn_search": fetch_hn_search, "hn_front": fetch_hn_front}


def tidy(item):
    """Clean source boilerplate the feeds leak into titles/summaries (found by reviewing the UI mockups)."""
    title, summary = item["title"], item.get("summary", "")
    if " -- by " in title:                       # NBER: "Paper title -- by A, B, C"
        title, authors = title.split(" -- by ", 1)
        item["meta"]["authors"] = authors.strip()[:200]
    summary = re.sub(r"\s*submitted by\s+/u/\S+\s*(\[link\])?\s*(\[comments\])?\s*$", "", summary).strip()
    if not re.sub(r"https?://\S+", "", summary).strip():   # only URLs, no words: not a summary
        summary = ""
    item["title"], item["summary"] = title.strip(), summary
    return item


def fetch_source(src):
    return [tidy(it) for it in FETCHERS[src["kind"]](src)]
