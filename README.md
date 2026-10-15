# Marketing Scouter

Command-driven, read-only, human-gated. You click Scout; it fetches public sources, Jev ranks each item
against your interests, and Hermes drafts a proposed post when you ask. **Nothing here can publish.**

```
sources.json ──fetch──▶ store (SQLite) ──Jev: 1 noul per interest──▶ ranked queue ──you open one──▶ Hermes draft
 op-eds / trends /         dedupe by URL        relevance = max p, lens = argmax        take (yours, verbatim)
 commentary                                                                            + profile.md + source
```

## Run

```
python3 -m scouter scout [--panel op-eds|trends|commentary] [--source ID] [--rescore]
python3 -m scouter list  [--panel P] [--min 0.15]
python3 -m scouter draft ID [--take "your own thought"]
python3 -m scouter capture URL [--text "..."]     # X post via oEmbed, or pasted text
python3 -m scouter status ID approved|dismissed
python3 -m scouter serve --open                   # the dashboard at http://127.0.0.1:8787 (127.0.0.1 only)
python3 -m unittest discover -s tests -t .
```

## The dashboard (`web/`, vanilla JS, no build step)
Editorial broadsheet: three columns (op-eds, trends, commentary), warm glass on hover, and clicking a card
opens a two-page workspace: the source and why it surfaced on the left, your desk on the right.

1. **Scout** (top left) fetches and scores; nothing runs on a schedule.
2. Click a card. Write **your take** (optional, stored verbatim), then ask Hermes to draft.
3. Read Hermes's notes and tick its checklist, edit the draft (saved as its own "yours" version), **Copy**, paste it yourself.
4. **Approve** only records your decision here. There is no send button anywhere.

`Esc` closes the workspace. Takes you type are kept in the browser even if you leave before drafting.

## Files you edit
| file | what |
|---|---|
| `interests.json` | topics Jev scores against (name + one-line description; topic-level only, it is sent to Jev) |
| `sources.json` | feeds and queries per panel, `min_relevance` display floor |
| `profile.md` | voice, positions, hard limits sent to the drafting model (**edit the placeholder positions**) |
| `settings.json` | drafting model/provider, per-panel format rules |

Key: `TYPESAFE_API_KEY` in `~/.hermes/.env` (never printed or logged). Python 3.9 stdlib only.

## Design rules
- Jev decides (atomic yes/no per interest), Hermes writes. Neither does the other's job.
- Your take is stored verbatim and never overwritten; model text is labelled a suggestion.
- A failed source/score/draft is reported and skipped, never faked. Unscored items retry next run.
- Changing `interests.json` marks old scores stale; `scout` rescoring picks them up automatically.
- `state/` (database) is local and git-ignored.

## Known limits (2026-10-06)
- Reddit unauthenticated RSS returns 429 after the first request or two. Proper fix: a free Reddit script app (OAuth).
- X discovery is off (xAI credits). X = paste-a-URL only. LinkedIn = paste text.
- "Trends" persistence is approximated by a 14-day HN window with a points floor; no cross-day clustering yet.
- Latin American economy matches most Argentine economic news at 0.6 to 0.9: relevance is not the same as opportunity.
