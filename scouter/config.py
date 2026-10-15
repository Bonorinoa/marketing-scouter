"""Shared paths, config loading and the API key. Stdlib only (Python 3.9+)."""
import hashlib
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from html import unescape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.join(ROOT, "state")
DB_PATH = os.path.join(STATE_DIR, "scouter.db")
UA = "marketing-scouter/0.1 (personal research tool; read-only)"


def load_json(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return json.load(f)


def interests():
    return load_json("interests.json")


def interests_version():
    """Hash of the interests file, so changing interests marks old scores stale."""
    with open(os.path.join(ROOT, "interests.json"), "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:10]


def sources():
    return load_json("sources.json")


def env_value(name, path=None):
    """Read NAME from the process env, else from ~/.hermes/.env. Never printed or logged."""
    if os.environ.get(name):
        return os.environ[name]
    path = path or os.path.expanduser("~/.hermes/.env")
    try:
        for line in open(path, encoding="utf-8"):
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return None


def clean_text(s, limit=None):
    """Strip tags/entities and collapse whitespace."""
    out = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(s or ""))).strip()
    if limit and len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0].rstrip(",;:.") + "…"     # cut at a word, say so
    return out


def http_get(url, timeout=25, headers=None):
    """GET -> (status, text). Never raises on HTTP errors; raises OSError on network failure."""
    req = urllib.request.Request(url, headers=dict({"User-Agent": UA}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        raise OSError("network error for %s: %s" % (url, e.reason))
