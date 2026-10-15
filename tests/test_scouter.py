"""Offline unit tests for Marketing Scouter.  Python 3.9+, stdlib only (unittest + unittest.mock)."""

import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, MagicMock, call
from io import BytesIO
from http.server import ThreadingHTTPServer
import http.client
import urllib.error
import urllib.request

# -- ensure the project root is on sys.path so "import scouter" and its relatives work
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.abspath(os.path.join(_HERE, ".."))
if _PROJECT not in sys.path:
    sys.path.insert(0, _PROJECT)

import scouter.config as config
import scouter.sources as sources
import scouter.store as store
import scouter.jev as jev
import scouter.draft as draft
import scouter.server as server
import scouter.scout as scout  # noqa: F811  (module name shadows scout.run)
import scouter


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _with_temp_db(test_method):
    """Decorator that patches DB_PATH and STATE_DIR to a temporary directory."""
    def wrapper(self):
        with tempfile.TemporaryDirectory(prefix="scouter_test_") as tmp:
            with patch.object(config, "DB_PATH", os.path.join(tmp, "scouter.db")):
                with patch.object(config, "STATE_DIR", tmp):
                    test_method(self)
    return wrapper


def _with_temp_db_no_teardown(test_method):
    """Decorator-like helper that yields (tmp, db) — used when the test needs
    the db object and the tmpdir to stay alive through the test."""
    # This is implemented as a method so we don't need a decorator for every test
    pass


# ---------------------------------------------------------------------------
#  (a) sources.candidate_id
# ---------------------------------------------------------------------------

class TestCandidateId(unittest.TestCase):

    def test_stable_and_12_chars(self):
        url = "https://example.com/article-123"
        cid = sources.candidate_id(url)
        self.assertEqual(len(cid), 12)
        self.assertEqual(cid, sources.candidate_id(url))
        self.assertNotEqual(cid, sources.candidate_id("https://other.com"))


# ---------------------------------------------------------------------------
#  (b) sources.fetch_rss
# ---------------------------------------------------------------------------

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>First Article</title>
      <link>http://example.com/1</link>
      <description>Short description one</description>
      <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Second Article</title>
      <link>http://example.com/2</link>
      <description>Short description two</description>
      <pubDate>Tue, 02 Jan 2024 00:00:00 GMT</pubDate>
    </item>
    <item>
      <title></title>
      <link>http://example.com/3</link>
      <description>No title</description>
    </item>
    <item>
      <title>No Link</title>
      <link></link>
      <description>Missing link</description>
    </item>
  </channel>
</rss>"""

ATOM_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Atom Post</title>
    <link href="http://example.com/atom1"/>
    <summary>Atom summary text</summary>
    <published>2024-01-03T00:00:00Z</published>
  </entry>
</feed>"""


class TestFetchRss(unittest.TestCase):

    def _src(self, url="http://test.feed/rss", limit=25):
        return {"id": "test_rss", "panel": "test", "url": url, "limit": limit, "lang": "en"}

    def test_parses_rss_20(self):
        src = self._src()
        with patch.object(config, "http_get", return_value=(200, RSS_SAMPLE)):
            items = sources.fetch_rss(src)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "First Article")
        self.assertEqual(items[0]["url"], "http://example.com/1")
        self.assertEqual(items[1]["title"], "Second Article")
        self.assertEqual(items[1]["url"], "http://example.com/2")
        self.assertEqual(items[0]["panel"], "test")
        self.assertEqual(items[0]["source"], "test_rss")

    def test_parses_atom(self):
        src = self._src()
        with patch.object(config, "http_get", return_value=(200, ATOM_SAMPLE)):
            items = sources.fetch_rss(src)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Atom Post")
        self.assertEqual(items[0]["url"], "http://example.com/atom1")

    def test_respects_limit(self):
        src = self._src(limit=1)
        with patch.object(config, "http_get", return_value=(200, RSS_SAMPLE)):
            items = sources.fetch_rss(src)
        self.assertEqual(len(items), 1)

    def test_skips_entries_without_title_or_link(self):
        """Items missing title or link are omitted."""
        src = self._src()
        with patch.object(config, "http_get", return_value=(200, RSS_SAMPLE)):
            items = sources.fetch_rss(src)
        titles = [i["title"] for i in items]
        self.assertNotIn("No Link", titles)
        # The item with empty title is also skipped; only the first two survive.

    def test_raises_oserror_on_non_200(self):
        src = self._src()
        with patch.object(config, "http_get", return_value=(404, "Not Found")):
            with self.assertRaises(OSError):
                sources.fetch_rss(src)


# ---------------------------------------------------------------------------
#  (c) sources.fetch_hn_search / fetch_hn_front
# ---------------------------------------------------------------------------

HN_HITS = [
    {"objectID": "001", "title": "Story One", "story_text": "Text of story one",
     "created_at": "2024-01-01T00:00:00Z", "points": 50, "num_comments": 10, "url": "http://ext1.com"},
    {"objectID": "002", "title": "Story Two", "story_text": None,
     "created_at": "2024-01-02T00:00:00Z", "points": 30, "num_comments": 5, "url": ""},
    {"objectID": "003", "title": "", "story_text": "no title text",
     "created_at": "", "points": 5, "num_comments": 0, "url": None},
]


class TestHNSearch(unittest.TestCase):

    def _src(self):
        return {"id": "hn_test", "panel": "trends", "days": 14, "min_points": 15,
                "per_query": 15, "queries": ["causal inference", "AI"]}

    def test_maps_hits_to_candidates(self):
        src = self._src()
        with patch.object(sources, "_hn_get", return_value=HN_HITS):
            items = sources.fetch_hn_search(src)
        # hit 003 has empty title → skipped
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "Story One")
        self.assertEqual(items[0]["source"], "hn_test")
        self.assertEqual(items[0]["meta"]["points"], 50)
        self.assertEqual(items[0]["meta"]["external_url"], "http://ext1.com")
        self.assertIn("query", items[0]["meta"])

    def test_deduplicates_across_queries(self):
        src = self._src()
        # same hit returned for both queries
        with patch.object(sources, "_hn_get", return_value=[HN_HITS[0]]):
            items = sources.fetch_hn_search(src)
        self.assertEqual(len(items), 1)


class TestHNFront(unittest.TestCase):

    def _src(self):
        return {"id": "hn_front_test", "panel": "commentary", "limit": 30}

    def test_maps_hits_to_candidates(self):
        src = self._src()
        with patch.object(sources, "_hn_get", return_value=HN_HITS):
            items = sources.fetch_hn_front(src)
        self.assertEqual(len(items), 2)  # hit 003 filtered out (no title)
        self.assertEqual(items[0]["url"], "https://news.ycombinator.com/item?id=001")


# ---------------------------------------------------------------------------
#  (d) store
# ---------------------------------------------------------------------------

class TestStore(unittest.TestCase):

    def _db(self, tmp):
        return store.connect(os.path.join(tmp, "scouter.db"))

    def _item(self, url, title="Some Title"):
        return {"panel": "test", "source": "test_src", "title": title,
                "url": url, "summary": "summary", "published": "",
                "meta": {"lang": "en"}}

    # -- upsert is idempotent and never overwrites an existing score ----------

    @_with_temp_db
    def test_upsert_idempotent_does_not_overwrite_score(self):
        db = self._db(config.DB_PATH.rsplit("/", 1)[0])
        db = store.connect()  # re-read from patched path
        # Use a simpler approach: get the tmp dir from the patched DB_PATH
        # Since _with_temp_db decorator wraps, let's inline
        pass


# Because the decorator approach above is awkward, use a setUp/tearDown
# pattern with manual temp dirs.

class TestStoreDirect(unittest.TestCase):
    """Store tests with explicit temp dir management."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="scouter_store_")
        self.db_path = os.path.join(self.tmp, "scouter.db")
        self.db = store.connect(self.db_path)

    def tearDown(self):
        self.db.close()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # convenience
    def _item(self, url, title="Some Title"):
        return {"panel": "test", "source": "test_src", "title": title,
                "url": url, "summary": "summary", "published": "",
                "meta": {"lang": "en"}}

    # ---- upsert idempotent ------------------------------------------------

    def test_upsert_idempotent_no_score_overwrite(self):
        url = "http://example.com/unique"
        items = [self._item(url)]
        new_ids = store.upsert_candidates(self.db, items)
        self.assertEqual(len(new_ids), 1)
        cid = new_ids[0]
        # score it
        store.save_score(self.db, cid, "v1",
                         {"relevance": 0.9, "lens": "test", "scores": {"AI": 0.9},
                          "personal": 0.0, "input_tokens": 50, "cost_usd": 0.0, "ms": 100})
        # upsert same URL again
        new_ids2 = store.upsert_candidates(self.db, items)
        self.assertEqual(len(new_ids2), 0)  # no new rows
        row = store.get_candidate(self.db, cid)
        self.assertIsNotNone(row)
        self.assertEqual(row["relevance"], 0.9)  # score preserved

    # ---- unscored ---------------------------------------------------------

    def test_unscored_returns_only_items_with_different_scored_with(self):
        url1 = "http://example.com/a"
        url2 = "http://example.com/b"
        ids = store.upsert_candidates(self.db, [self._item(url1), self._item(url2)])
        # both are unscored → both returned
        todo = store.unscored(self.db, "v1")
        self.assertEqual(len(todo), 2)
        # score item A
        store.save_score(self.db, ids[0], "v1",
                         {"relevance": 0.5, "lens": "t", "scores": {"X": 0.5},
                          "personal": 0.0, "input_tokens": 10, "cost_usd": 0.0, "ms": 5})
        todo = store.unscored(self.db, "v1")
        self.assertEqual(len(todo), 1)
        self.assertEqual(todo[0]["id"], ids[1])
        # different version → included
        todo = store.unscored(self.db, "v2")
        self.assertEqual(len(todo), 2)
        # rescore=True → included
        todo = store.unscored(self.db, "v1", rescore=True)
        self.assertEqual(len(todo), 2)

    # ---- list_candidates --------------------------------------------------

    def test_list_candidates_respects_min_relevance(self):
        url1 = "http://ex.com/high"
        url2 = "http://ex.com/low"
        ids = store.upsert_candidates(self.db, [self._item(url1), self._item(url2)])
        store.save_score(self.db, ids[0], "v1",
                         {"relevance": 0.8, "lens": "t", "scores": {"X": 0.8},
                          "personal": 0.0, "input_tokens": 0, "cost_usd": 0.0, "ms": 0})
        store.save_score(self.db, ids[1], "v1",
                         {"relevance": 0.1, "lens": "t", "scores": {"Y": 0.1},
                          "personal": 0.0, "input_tokens": 0, "cost_usd": 0.0, "ms": 0})
        rows = store.list_candidates(self.db, min_relevance=0.5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], ids[0])
        rows_all = store.list_candidates(self.db, min_relevance=0.0)
        self.assertEqual(len(rows_all), 2)

    def test_list_candidates_excludes_dismissed_by_default(self):
        ids = store.upsert_candidates(self.db, [self._item("http://ex.com/ok")])
        store.save_score(self.db, ids[0], "v1",
                         {"relevance": 0.5, "lens": "t", "scores": {"X": 0.5},
                          "personal": 0.0, "input_tokens": 0, "cost_usd": 0.0, "ms": 0})
        store.set_status(self.db, ids[0], "dismissed")
        rows = store.list_candidates(self.db)
        self.assertEqual(len(rows), 0)
        rows = store.list_candidates(self.db, status="dismissed")
        self.assertEqual(len(rows), 1)

    # ---- set_status -------------------------------------------------------

    def test_set_status_rejects_unknown(self):
        ids = store.upsert_candidates(self.db, [self._item("http://ex.com/x")])
        with self.assertRaises(ValueError):
            store.set_status(self.db, ids[0], "unknown")

    # ---- add_draft flips new→drafted; leaves approved untouched -----------

    def test_add_draft_flips_new_to_drafted(self):
        ids = store.upsert_candidates(self.db, [self._item("http://ex.com/draft1")])
        cid = ids[0]
        store.save_score(self.db, cid, "v1",
                         {"relevance": 0.5, "lens": "t", "scores": {"X": 0.5},
                          "personal": 0.0, "input_tokens": 0, "cost_usd": 0.0, "ms": 0})
        store.add_draft(self.db, cid, "my take", "lens", "draft text",
                        "rationale", [], "test-model")
        c = store.get_candidate(self.db, cid)
        self.assertEqual(c["status"], "drafted")

    def test_add_draft_leaves_approved_untouched(self):
        ids = store.upsert_candidates(self.db, [self._item("http://ex.com/draft2")])
        cid = ids[0]
        store.save_score(self.db, cid, "v1",
                         {"relevance": 0.5, "lens": "t", "scores": {"X": 0.5},
                          "personal": 0.0, "input_tokens": 0, "cost_usd": 0.0, "ms": 0})
        store.set_status(self.db, cid, "approved")
        store.add_draft(self.db, cid, "", "lens", "text", "r", [], "m")
        c = store.get_candidate(self.db, cid)
        self.assertEqual(c["status"], "approved")

    # ---- drafts are append-only -------------------------------------------

    def test_drafts_append_only(self):
        ids = store.upsert_candidates(self.db, [self._item("http://ex.com/draft3")])
        cid = ids[0]
        store.save_score(self.db, cid, "v1",
                         {"relevance": 0.5, "lens": "t", "scores": {"X": 0.5},
                          "personal": 0.0, "input_tokens": 0, "cost_usd": 0.0, "ms": 0})
        d1 = store.add_draft(self.db, cid, "take A", "lens", "text A", "r", [], "m")
        d2 = store.add_draft(self.db, cid, "take B", "lens", "text B", "r", [], "m")
        self.assertNotEqual(d1, d2)
        drafts = store.list_drafts(self.db, cid)
        self.assertEqual(len(drafts), 2)


# ---------------------------------------------------------------------------
#  (e) jev
# ---------------------------------------------------------------------------

INTERESTS_SAMPLE = [
    {"name": "AI and society", "description": "AI ethics and policy"},
    {"name": "Formal methods", "description": "Lean, verification"},
]

SCORE_RESP = {"answers": {"i0": {"noul": 0.9}, "i1": {"noul": 0.3},
                           "personal": {"noul": 0.0}},
              "usage": {"input_tokens": 100}}


class TestJev(unittest.TestCase):

    # -- relevance_questions ------------------------------------------------

    def test_relevance_questions_builds_one_noul_per_interest_plus_personal(self):
        qs = jev.relevance_questions(INTERESTS_SAMPLE)
        self.assertIn("i0", qs)
        self.assertIn("i1", qs)
        self.assertIn("personal", qs)
        self.assertEqual(qs["i0"]["type"], "noul")
        self.assertEqual(qs["personal"]["type"], "noul")

    def test_question_ids_map_back_by_position(self):
        qs = jev.relevance_questions(INTERESTS_SAMPLE)
        self.assertIn("AI and society", qs["i0"]["instructions"])
        self.assertIn("Formal methods", qs["i1"]["instructions"])

    # -- score_item ---------------------------------------------------------

    @patch.object(jev, "_post", return_value=SCORE_RESP)
    def test_score_item_picks_argmax_lens(self, mock_post):
        result = jev.score_item("dummy-key", {"source": "t", "title": "Test"},
                                INTERESTS_SAMPLE)
        self.assertEqual(result["lens"], "AI and society")  # 0.9 > 0.3
        self.assertAlmostEqual(result["relevance"], 0.9)
        self.assertEqual(result["input_tokens"], 100)

    @patch.object(jev, "_post")
    def test_score_item_raises_jeverror_on_missing_answer(self, mock_post):
        incomplete = {"answers": {"i0": {"noul": 0.5}}, "usage": {}}
        mock_post.return_value = incomplete
        with self.assertRaises(jev.JevError):
            jev.score_item("k", {"source": "t", "title": "T"}, INTERESTS_SAMPLE)

    # -- JevError never contains the API key --------------------------------

    def test_jeverror_no_key_leak(self):
        """The JevError message must redact the API key even when the HTTP
        error body echoes it."""
        key = "sk-live-secret-12345"
        body_bytes = ('{"error": "invalid api key: ' + key + '"}').encode("utf-8")
        fp = BytesIO(body_bytes)
        http_error = urllib.error.HTTPError(
            "https://api.typesafe.ai/v1/systemone", 401, "Unauthorized",
            {"Content-Type": "application/json"}, fp)

        with patch("urllib.request.urlopen", side_effect=http_error):
            with self.assertRaises(jev.JevError) as ctx:
                jev._post(key, {}, [])
        self.assertNotIn(key, str(ctx.exception))
        # sanity: the message is informative
        self.assertIn("Jev HTTP", str(ctx.exception))


# ---------------------------------------------------------------------------
#  (f) scout.run
# ---------------------------------------------------------------------------

class TestScoutRun(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="scouter_scout_")
        self.db_path = os.path.join(self.tmp, "scouter.db")
        # patch db path before any store.connect calls
        self.db_patch = patch.object(config, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.state_patch = patch.object(config, "STATE_DIR", self.tmp)
        self.state_patch.start()
        # create the DB so store.connect() works
        store.connect(self.db_path).close()

    def tearDown(self):
        self.state_patch.stop()
        self.db_patch.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _score_result(self, lens="AI", relevance=0.8):
        return {"relevance": relevance, "lens": lens,
                "scores": {"AI": relevance}, "personal": 0.0,
                "input_tokens": 10, "cost_usd": 4.2e-7, "ms": 50}

    def test_counts_are_right(self):
        with patch.object(config, "env_value", return_value="dummy-key"):
            with patch.object(config, "sources") as mock_src:
                mock_src.return_value = {
                    "min_relevance": 0.15,
                    "sources": [{"id": "src_a", "panel": "test", "kind": "rss"}]
                }
                with patch.object(sources, "fetch_source",
                                  return_value=[{"panel": "test", "source": "src_a",
                                                  "title": "Item", "url": "http://ex.com/a",
                                                  "summary": "", "published": "",
                                                  "meta": {}}]):
                    with patch.object(jev, "score_item",
                                      return_value=self._score_result()):
                        s = scout.run(log=lambda _: None)
        self.assertEqual(s["fetched"], 1)
        self.assertEqual(s["new"], 1)
        self.assertEqual(s["scored"], 1)
        self.assertEqual(s["failed_sources"], [])
        self.assertEqual(s["failed_items"], 0)

    def test_failing_source_is_reported_and_skipped(self):
        with patch.object(config, "env_value", return_value="dummy-key"):
            with patch.object(config, "sources") as mock_src:
                mock_src.return_value = {
                    "min_relevance": 0.15,
                    "sources": [
                        {"id": "src_good", "panel": "test", "kind": "rss"},
                        {"id": "src_bad", "panel": "test", "kind": "rss"},
                    ]
                }
                call_count = 0

                def _fetch(src):
                    nonlocal call_count
                    call_count += 1
                    if src["id"] == "src_bad":
                        raise OSError("timeout")
                    return [{"panel": "test", "source": "src_good",
                             "title": "Item", "url": "http://ex.com/g",
                             "summary": "", "published": "", "meta": {}}]

                with patch.object(sources, "fetch_source", side_effect=_fetch):
                    with patch.object(jev, "score_item",
                                      return_value=self._score_result()):
                        s = scout.run(log=lambda _: None)
        self.assertEqual(s["fetched"], 1)
        self.assertEqual(s["failed_sources"], ["src_bad"])
        self.assertEqual(s["failed_items"], 0)

    def test_item_whose_scoring_raises_jeve_stays_unscored(self):
        with patch.object(config, "env_value", return_value="dummy-key"):
            with patch.object(config, "sources") as mock_src:
                mock_src.return_value = {
                    "min_relevance": 0.15,
                    "sources": [{"id": "src_a", "panel": "test", "kind": "rss"}]
                }
                with patch.object(sources, "fetch_source",
                                  return_value=[{"panel": "test", "source": "src_a",
                                                  "title": "Item", "url": "http://ex.com/f",
                                                  "summary": "", "published": "",
                                                  "meta": {}}]):
                    with patch.object(jev, "score_item",
                                      side_effect=jev.JevError("Jev HTTP 500")):
                        s = scout.run(log=lambda _: None)
        self.assertEqual(s["fetched"], 1)
        self.assertEqual(s["new"], 1)
        self.assertEqual(s["scored"], 0)
        self.assertEqual(s["failed_items"], 1)

    def test_second_run_does_not_rescore_but_rescore_flag_does(self):
        with patch.object(config, "env_value", return_value="dummy-key"):
            with patch.object(config, "sources") as mock_src:
                mock_src.return_value = {
                    "min_relevance": 0.15,
                    "sources": [{"id": "src_a", "panel": "test", "kind": "rss"}]
                }
                items = [{"panel": "test", "source": "src_a",
                          "title": "Item", "url": "http://ex.com/r",
                          "summary": "", "published": "", "meta": {}}]
                with patch.object(sources, "fetch_source", return_value=items):
                    with patch.object(jev, "score_item",
                                      return_value=self._score_result()) as mock_score:
                        # first run → 1 scored
                        s1 = scout.run(log=lambda _: None)
                        self.assertEqual(s1["scored"], 1)
                        # second run → should not rescore (scored_with matches version)
                        s2 = scout.run(log=lambda _: None)
                        self.assertEqual(s2["scored"], 0)
                        # third run with rescore=True → rescored
                        s3 = scout.run(rescore=True, log=lambda _: None)
                        self.assertEqual(s3["scored"], 1)
                        # verify score_item was called exactly twice (first + rescore)
                        self.assertEqual(mock_score.call_count, 2)


# ---------------------------------------------------------------------------
#  (g) draft.parse_reply / draft.make_draft
# ---------------------------------------------------------------------------

class TestDraftParseReply(unittest.TestCase):

    def test_accepts_clean_json(self):
        obj = draft.parse_reply('{"draft": "hello", "rationale": "good", "flags": []}')
        self.assertEqual(obj["draft"], "hello")
        self.assertEqual(obj["rationale"], "good")
        self.assertEqual(obj["flags"], [])

    def test_extracts_json_from_surrounding_prose(self):
        text = "Some preamble text\n\n{\"draft\": \"nested\", \"rationale\": \"ok\", \"flags\": [\"check\"]}\n\nmore after"
        obj = draft.parse_reply(text)
        self.assertEqual(obj["draft"], "nested")

    def test_rejects_empty_text(self):
        with self.assertRaises(ValueError):
            draft.parse_reply("")

    def test_rejects_non_json_text(self):
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            draft.parse_reply("this is just plain text without any JSON")


class TestDraftMakeDraft(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="scouter_draft_")
        self.db_path = os.path.join(self.tmp, "scouter.db")
        self.db = store.connect(self.db_path)
        # insert a candidate
        ids = store.upsert_candidates(self.db, [{
            "panel": "trends", "source": "test_s", "title": "Candidate",
            "url": "http://ex.com/cand", "summary": "sum", "published": "",
            "meta": {"lang": "en"}
        }])
        self.cid = ids[0]
        store.save_score(self.db, self.cid, "v1",
                         {"relevance": 0.8, "lens": "AI", "scores": {"AI": 0.8},
                          "personal": 0.0, "input_tokens": 10, "cost_usd": 0.0, "ms": 0})
        self.db.close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @patch.object(draft, "run_hermes")
    def test_make_draft_saves_nothing_and_raises_when_reply_unusable(self, mock_run):
        mock_run.return_value = ("this is not json", {})
        db = store.connect(self.db_path)
        with patch.object(config, "DB_PATH", self.db_path):
            with patch.object(config, "STATE_DIR", self.tmp):
                with self.assertRaises(RuntimeError):
                    draft.make_draft(self.cid, db=db)
        db.close()
        # verify no draft was saved
        db2 = store.connect(self.db_path)
        self.assertEqual(len(store.list_drafts(db2, self.cid)), 0)
        db2.close()

    @patch.object(draft, "run_hermes")
    def test_user_take_stored_verbatim(self, mock_run):
        mock_run.return_value = ('{"draft": "proposed text", "rationale": "my reason", "flags": []}', {})
        db = store.connect(self.db_path)
        user_take = "My own thought here. Verbatim."
        with patch.object(config, "DB_PATH", self.db_path):
            with patch.object(config, "STATE_DIR", self.tmp):
                result = draft.make_draft(self.cid, user_take=user_take, db=db)
        db.close()
        db2 = store.connect(self.db_path)
        drafts = store.list_drafts(db2, self.cid)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["user_take"], user_take)
        db2.close()


# ---------------------------------------------------------------------------
#  (h) server
# ---------------------------------------------------------------------------

class TestServer(unittest.TestCase):
    """Start the handler on an ephemeral port in a daemon thread."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="scouter_srv_")
        cls.db_path = os.path.join(cls.tmp, "scouter.db")
        # patch DB_PATH so the server uses the temp db
        cls._db_patch = patch.object(config, "DB_PATH", cls.db_path)
        cls._db_patch.start()
        cls._state_patch = patch.object(config, "STATE_DIR", cls.tmp)
        cls._state_patch.start()
        # seed a candidate
        db = store.connect(cls.db_path)
        ids = store.upsert_candidates(db, [{
            "panel": "test", "source": "test_s", "title": "SrvCand",
            "url": "http://ex.com/srv", "summary": "", "published": "",
            "meta": {}
        }])
        cls.cid = ids[0]
        store.save_score(db, cls.cid, "v1",
                         {"relevance": 0.6, "lens": "AI", "scores": {"AI": 0.6},
                          "personal": 0.0, "input_tokens": 0, "cost_usd": 0.0, "ms": 0})
        db.close()
        # start server
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls._db_patch.stop()
        cls._state_patch.stop()
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- GET /api/state works -----------------------------------------------

    def test_get_api_state(self):
        resp = urllib.request.urlopen("http://127.0.0.1:%d/api/state" % self.port)
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode("utf-8"))
        self.assertIn("panels", data)
        self.assertIn("interests", data)
        self.assertIn("counts", data)

    # -- Bad Host header → 403 ----------------------------------------------

    def test_bad_host_returns_403(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", "/api/state", headers={"Host": "evil.com"})
        resp = conn.getresponse()
        body = resp.read()
        self.assertEqual(resp.status, 403)
        conn.close()

    # -- POST without JSON Content-Type → 415 --------------------------------

    def test_post_without_json_content_type_returns_415(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("POST", "/api/status", body=b'{"id":"x","status":"drafted"}',
                     headers={"Content-Type": "text/plain"})
        resp = conn.getresponse()
        body = resp.read()
        self.assertEqual(resp.status, 415)
        conn.close()

    # -- POST /api/status updates a candidate --------------------------------

    def test_post_status_updates_candidate(self):
        data = json.dumps({"id": self.cid, "status": "approved"}).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/status" % self.port, data=data,
            headers={"Content-Type": "application/json"},
            method="POST")
        resp = urllib.request.urlopen(req)
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.read().decode("utf-8"))
        self.assertTrue(body.get("ok"))
        # verify the db was updated
        db = store.connect(self.db_path)
        c = store.get_candidate(db, self.cid)
        self.assertEqual(c["status"], "approved")
        db.close()

    # -- Unknown POST route → 404 --------------------------------------------

    def test_unknown_post_route_returns_404(self):
        data = json.dumps({"a": 1}).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/nonexistent" % self.port, data=data,
            headers={"Content-Type": "application/json"},
            method="POST")
        try:
            urllib.request.urlopen(req)
            self.fail("expected HTTPError")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)
            body = json.loads(e.read().decode("utf-8"))
            self.assertIn("error", body)

    # -- human edits are stored as their own version ---------------------------

    def test_save_edit_is_a_separate_labelled_version(self):
        data = json.dumps({"id": self.cid, "text": "my edited words", "take": "my take"}).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:%d/api/draft/save" % self.port, data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        self.assertEqual(urllib.request.urlopen(req).status, 200)
        db = store.connect(self.db_path)
        d = store.list_drafts(db, self.cid)[0]
        self.assertEqual((d["text"], d["model"], d["user_take"]), ("my edited words", "you (edited)", "my take"))
        db.close()

    def test_save_edit_rejects_empty_text(self):
        data = json.dumps({"id": self.cid, "text": "   "}).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:%d/api/draft/save" % self.port, data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)

    # -- static files: index is served, nothing outside web/ is --------------

    def test_index_is_served(self):
        resp = urllib.request.urlopen("http://127.0.0.1:%d/" % self.port)
        self.assertEqual(resp.status, 200)
        self.assertIn(b"Marketing Scouter", resp.read())

    def test_path_traversal_is_refused(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", "/../scouter/config.py")
        self.assertEqual(conn.getresponse().status, 404)
        conn.close()


# ---------------------------------------------------------------------------
#  Guard: no publishing strings in scouter source
# ---------------------------------------------------------------------------

class TestGuard(unittest.TestCase):

    def test_no_publishing_strings(self):
        pkg_dir = os.path.dirname(scouter.__file__)
        forbiddden = {"smtp", "tweepy", "statuses/update"}
        found = {}
        for fname in sorted(os.listdir(pkg_dir)):
            if not fname.endswith(".py"):
                continue
            path = os.path.join(pkg_dir, fname)
            with open(path, encoding="utf-8") as f:
                content = f.read()
            for bad in forbiddden:
                if bad in content:
                    found.setdefault(bad, []).append(fname)
        if found:
            lines = []
            for bad, files in found.items():
                lines.append("  %r found in %s" % (bad, ", ".join(files)))
            self.fail("publishing-related strings found:\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
#  Run if called directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()

class TestTidy(unittest.TestCase):
    """Boilerplate found by reviewing the UI mockups (Reddit, NBER, HN)."""

    def _item(self, title, summary=""):
        return {"title": title, "summary": summary, "meta": {}}

    def test_nber_author_suffix_moves_to_meta(self):
        it = sources.tidy(self._item("Avoiding Regulation -- by Alden Cheng, Ri Chen"))
        self.assertEqual(it["title"], "Avoiding Regulation")
        self.assertIn("Alden Cheng", it["meta"]["authors"])

    def test_reddit_submitted_by_is_removed(self):
        it = sources.tidy(self._item("t", "A real sentence. submitted by /u/someone [link] [comments]"))
        self.assertEqual(it["summary"], "A real sentence.")

    def test_bare_url_summary_is_dropped(self):
        self.assertEqual(sources.tidy(self._item("t", "https://github.com/openai/math"))["summary"], "")

    def test_several_bare_urls_are_dropped(self):
        self.assertEqual(sources.tidy(self._item("t", "https://a.com/x https://a.com/y"))["summary"], "")

    def test_normal_item_untouched(self):
        it = sources.tidy(self._item("Dólar e inflación", "Texto normal."))
        self.assertEqual((it["title"], it["summary"]), ("Dólar e inflación", "Texto normal."))


class TestCleanText(unittest.TestCase):
    def test_truncates_at_a_word_with_ellipsis(self):
        from scouter import config
        out = config.clean_text("alpha beta gamma delta epsilon", 14)
        self.assertEqual(out, "alpha beta…")

    def test_short_text_untouched(self):
        from scouter import config
        self.assertEqual(config.clean_text("  hello   <b>world</b> ", 50), "hello world")
