"""CLI:  python3 -m scouter <command>

  scout [--panel P] [--source S] [--rescore]   fetch sources, score with Jev, store
  list  [--panel P] [--min 0.15] [--limit 15]  show the ranked queue
  draft ID [--take "my own thought"]           ask Hermes for a proposed post (never published)
  capture URL [--text "pasted text"] [--panel P]   add one item by hand (X/LinkedIn paste-a-URL path)
  status ID new|drafted|approved|dismissed     record your decision
  serve [--port 8787] [--open]                 the dashboard + JSON API on 127.0.0.1
"""
import argparse
import json
import sys

from . import config, store


def cmd_scout(a):
    from . import scout
    scout.run(panel=a.panel, source=a.source, rescore=a.rescore)


def cmd_list(a):
    db = store.connect()
    floor = a.min if a.min is not None else config.sources().get("min_relevance", 0.15)
    rows = store.list_candidates(db, panel=a.panel, min_relevance=floor, limit=a.limit)
    for r in rows:
        print("%.2f %-9s %-18s %-8s %s | %s" % (r["relevance"], r["panel"], r["source"][:18], r["status"],
                                             r["id"], r["title"][:70]))
        print("     lens: %s%s" % (r["lens"], "   (personal-info flag %.2f)" % r["personal"] if r["personal"] > 0.3 else ""))
    print("%d item(s) at relevance >= %.2f" % (len(rows), floor))


def cmd_draft(a):
    from . import draft
    r = draft.make_draft(a.id, user_take=a.take)
    print(json.dumps(r, ensure_ascii=False, indent=2))


def cmd_capture(a):
    from . import capture
    print(json.dumps(capture.capture(a.url, text=a.text, panel=a.panel), ensure_ascii=False, indent=2))


def cmd_status(a):
    store.set_status(store.connect(), a.id, a.status)
    print("ok")


def cmd_serve(a):
    from . import server
    server.serve(a.port, open_browser=a.open)


def main(argv=None):
    p = argparse.ArgumentParser(prog="scouter", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scout"); s.add_argument("--panel"); s.add_argument("--source")
    s.add_argument("--rescore", action="store_true"); s.set_defaults(f=cmd_scout)
    s = sub.add_parser("list"); s.add_argument("--panel"); s.add_argument("--min", type=float)
    s.add_argument("--limit", type=int, default=15); s.set_defaults(f=cmd_list)
    s = sub.add_parser("draft"); s.add_argument("id"); s.add_argument("--take"); s.set_defaults(f=cmd_draft)
    s = sub.add_parser("capture"); s.add_argument("url"); s.add_argument("--text")
    s.add_argument("--panel", default="commentary"); s.set_defaults(f=cmd_capture)
    s = sub.add_parser("status"); s.add_argument("id"); s.add_argument("status"); s.set_defaults(f=cmd_status)
    s = sub.add_parser("serve"); s.add_argument("--port", type=int, default=8787)
    s.add_argument("--open", action="store_true", help="open the dashboard in your browser"); s.set_defaults(f=cmd_serve)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
