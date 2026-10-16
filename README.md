# Market Scouter

A personal tool that finds public X posts where one of my research claims is relevant, scores how worth replying they are, and drafts a suggested reply. It never posts, schedules, or acts as me. I write every final post myself, outside the tool.

Built by Augusto Gonzalez-Bonorino (@theholy_hermit) to support EconLLM Lab's research and to find collaborators, not to grow follower counts.

## How it works

1. **Discover.** Topic queries pull recent public posts. Every read is logged with its post id and config hash, and discovery skips a run rather than spend reads below a set daily floor.
2. **Fit.** Each post is matched against an inventory of my own claims, each with a stated caveat. A post that matches no claim gets no card.
3. **Score.** Six weighted factors produce the score. The formula lives in one file, `src/scorer.py`, so any card can be recomputed by hand.
4. **Draft.** A model writes a suggestion in my voice. A voice gate rejects drafts that mention accounts, use hashtags, emoji or excess length, and drafts that just restate the claim.

## The score

| Factor | Weight |
|---|---|
| Fit with a claim | 30 |
| Urgency (falls with age, then steps down after 48 hours) | 20 |
| Format fit | 15 |
| Evidence grade of the claim | 20 |
| Voice match | 15 |
| Effort cost | hand-set penalty, outside the 100 |

**Hand-set by the team and not yet fitted to outcomes.** A review of X's open-sourced ranking signals will inform planned changes to Urgency and Format fit. Likes never enter the score. Only claim-naming replies, warm introductions and stronger evidence count as wins.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.api.app:app --port 8710
cd web && npm install && npm run dev
pytest -q && (cd web && npm test)
```

Tests use made-up fixtures only. No real posts or third-party accounts ship in this repository.
