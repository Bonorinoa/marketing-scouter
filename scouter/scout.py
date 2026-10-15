"""The scout command: fetch -> dedupe -> Jev relevance fan-out -> store. Triggered manually, never scheduled.

Failures are contained: a source that errors is reported and skipped; an item Jev cannot score stays
unscored (never given a made-up score) and is retried on the next run.
"""
import time
from concurrent.futures import ThreadPoolExecutor

from . import config, jev, sources, store


def run(panel=None, source=None, rescore=False, workers=4, log=print):
    key = config.env_value("TYPESAFE_API_KEY")
    if not key:
        raise SystemExit("TYPESAFE_API_KEY not found (env or ~/.hermes/.env)")
    cfg = config.sources()
    interests = config.interests()
    version = config.interests_version()
    db = store.connect()
    started = time.time()

    chosen = [s for s in cfg["sources"] if (not panel or s["panel"] == panel) and (not source or s["id"] == source)]
    if not chosen:
        raise SystemExit("no sources match panel=%r source=%r" % (panel, source))

    summary = {"fetched": 0, "new": 0, "scored": 0, "failed_sources": [], "failed_items": 0,
               "tokens": 0, "cost_usd": 0.0}
    for src in chosen:
        try:
            items = sources.fetch_source(src)
        except Exception as e:                       # one bad source must not stop the run
            log("  ! %-20s %s" % (src["id"], e))
            summary["failed_sources"].append(src["id"])
            continue
        new = store.upsert_candidates(db, items)
        summary["fetched"] += len(items)
        summary["new"] += len(new)
        log("  . %-20s fetched %3d  new %3d" % (src["id"], len(items), len(new)))

    todo = store.unscored(db, version, only_panel=panel, only_source=source, rescore=rescore)
    log("scoring %d item(s) with Jev (%d interests)" % (len(todo), len(interests)))

    def work(cand):
        try:
            return cand["id"], jev.score_item(key, cand, interests), None
        except jev.JevError as e:
            return cand["id"], None, str(e)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for cid, result, err in pool.map(work, todo):
            if err:
                summary["failed_items"] += 1
                log("  ! jev: %s" % err)
                continue
            store.save_score(db, cid, version, result)
            summary["scored"] += 1
            summary["tokens"] += result["input_tokens"]
            summary["cost_usd"] += result["cost_usd"]

    summary["seconds"] = round(time.time() - started, 1)
    store.log(db, "scout", panel=panel, source=source, rescore=rescore, **summary)
    log("done: %s" % ", ".join("%s=%s" % kv for kv in summary.items()))
    return summary
