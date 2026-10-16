# Scouter observability + scoring schema (DA)
**Date:** 2026-09-09  
**Pairs with:** Researcher `SourceAdapter` lock · `MVP-DESIGN.md` §9–11 · `fit-tags.md`  
**Product gate:** human posts; system only scouts + drafts; never OAuth-as-poster

---

## 1. Pipeline (orchestration)

```mermaid
flowchart LR
  Inv[Inventory asset + claim-tags] --> Seeds[Query / slug seeds]
  Seeds --> Adapters
  subgraph Adapters
    MP[manual.paste]
    XS[x.seed]
    XO[x.official optional]
    LG[li.google_site]
    LP[li.paste]
  end
  Adapters --> Cand[Candidate[]]
  Cand --> Kill[S_safe hard kill]
  Kill -->|survivors| Score[Score S §9]
  Score --> Dec{decision}
  Dec -->|enqueue| Q[Open queue ≤7]
  Dec -->|replace| Q
  Dec -->|drop| LogD[drop log]
  Dec -->|watch| Watch[watch shelf]
  Q --> Human[Human: draft shown]
  Human --> Out{acted / edited / skipped}
  Out --> Wins[Win signals]
```

**Rule:** `x-algorithm` / playbooks feed **FormatPrior + Urgency + draft shape only** — never discovery ranking of a firehose.

---

## 2. Core data models

### 2.1 InventoryAsset
| Field | Type | Notes |
|-------|------|--------|
| `asset_id` | string | stable |
| `title` | string | |
| `url` | string? | Substack / arXiv / Medium / Gaceta |
| `modality` | `text` \| `text+image` | v0 |
| `slugs` | string[] | ⊂ `fit-tags.md` |
| `door_archive` | `EconLLM` \| … | usually EconLLM |
| `oped_status` | enum? | `draft→submitted→pending→published→atomize` |
| `evidence_grade` | `A` \| `B` \| `C` | ungated → don’t queue |

### 2.2 Candidate (adapter output)
| Field | Type | Notes |
|-------|------|--------|
| `candidate_id` | string | hash(url) ok |
| `adapter` | enum | `x.official` \| `x.seed` \| `li.google_site` \| `li.paste` \| `manual.paste` |
| `outlet` | `x` \| `linkedin` | |
| `url` | string | deep link |
| `title_or_snippet` | string | |
| `author` | string? | |
| `created_at` | datetime? | |
| `reply_count` | int? | X T |
| `quote_count` | int? | X T |
| `comment_count` | int? | LI T |
| `like_count` | int? | **informational only** — never drives score |
| `raw_meta` | object | opaque |

### 2.3 ScoredCard (queue row)
| Field | Type | Notes |
|-------|------|--------|
| `card_id` | string | |
| `candidate_id` | string | |
| `asset_id` | string | matched inventory |
| `slugs` | string[] | matched |
| `voice_door` | `EconLLM` \| `Augusto-civic` \| … | draft voice |
| `move_type` | enum | reply / quote / comment / … |
| `draft_text` | string | channel-shaped; suggests only |
| `S` | number | 0–100-ish after penalty |
| `factors` | object | see §3 |
| `T_status` | `ok` \| `unknown` | LI often unknown |
| `state` | enum | `open` \| `drafting` \| `awaiting_approval` \| `pinned` \| `watch` \| `done` \| `skipped` |
| `playbook_rule_ids` | string[] | display, not % lift |

### 2.4 ScoutRun (observability root)
| Field | Type |
|-------|------|
| `scout_run_id` | string (uuid) |
| `started_at` / `finished_at` | datetime |
| `adapter` | enum |
| `query_or_slug` | string |
| `candidates_n` | int |
| `events[]` | ScoutEvent |

### 2.5 ScoutEvent
```
{
  "scout_run_id": "...",
  "ts": "...",
  "kind": "discovered" | "killed" | "scored" | "decision" | "human" | "win",
  "candidate_id"?: "...",
  "card_id"?: "...",
  "kill_reasons"?: ["promo_cta", "bait", "folklore", ...],  // S_safe
  "factors"?: { "Fit": 0.8, "Urgency": 1.0, "FormatPrior": 0.7,
                "Evidence": 1.0, "DoorMatch": 1.0, "EffortPenalty": 0 },
  "S"?: 85.5,
  "decision"?: "enqueue" | "replace" | "drop" | "watch",
  "replaced_card_id"?: "...",
  "human"?: "acted" | "edited" | "skipped",
  "wins"?: ["claim_named_reply", "warm_intro", "evidence_ab"]
}
```

---

## 3. Scoring (canonical = §9 additive)

\[
S = 30 F + 20 U + 15 P + 20 E + 15 D - \mathrm{EffortPenalty}
\]

| Code | Factor | Source |
|------|--------|--------|
| F | Fit | slug match vs thread topic; empty → **0 → no card** |
| U | Urgency | age; X soft-penalize ≫48h |
| P | FormatPrior | playbook ordinals only {1.0,0.7,0.4} — **never** Buffer % / Feed SR |
| E | Evidence | A=1, B=0.6, C=0 |
| D | DoorMatch | voice_door hygiene |
| EffortPenalty | 0 / 10 / 25 | draft minutes |

**Traction T (Researcher rule) — soft input to Urgency or display badge, not a fake ER:**
- X: prefer higher `reply_count + quote_count` when age fresh; likes ignored for S
- LI: if `comment_count` missing → `T_status=unknown`; do **not** invent; Urgency from age/Fit only

Optional legacy multiplicative form \(R\cdot T\cdot C\cdot F\cdot S_{safe}\) maps as: R←Fit, C←contributable claim, F←Urgency, \(S_{safe}\)←hard kill (0/1), T←badge only. **Ship additive §9 in UI.**

---

## 4. Guardrails (hard)

| Guard | Enforcement |
|-------|-------------|
| Never auto-post / schedule | no publisher adapter in v0 |
| No OAuth-as-poster | adapters are read/seed/paste only |
| Cap 7 open / outlet | replace only if \(S_{new} \ge \min S_{unprot}+10\) |
| Protect drafting / awaiting_approval / pinned | never auto-drop |
| Fit empty = 0 | require ≥1 slug |
| Evidence C / ungated | don’t enqueue |
| DA KILL folklore | kill_reasons include folklore ids |
| Provincial press voice | `Augusto-civic`; no lab plug in draft |
| Op-ed not published | may scout civic threads; atomize only after `published` |

---

## 5. Weekly observability (human-facing)

Aggregate from events — **distribution wins only**:
1. Count `win:claim_named_reply`
2. Count `win:warm_intro`
3. Share of acted cards with Evidence A/B

**Do not report:** promised ER, Buffer medians as lifts, impression vanity as success.

---

## 6. Adapter capability matrix

| Adapter | discover | T fields | v0 |
|---------|----------|----------|-----|
| `manual.paste` | urls | maybe none until fetch | **ship** |
| `x.seed` | query→public search or “open these URLs” | reply/quote if fetch works | **ship** |
| `x.official` | bearer search | reply/quote/like | optional |
| `li.google_site` | SERP links | usually unknown | **ship** |
| `li.paste` | urls | maybe comment_count | **ship** |

---

## 7. Open handoff

- **Systems Designer:** use §1 mermaid + §2 models for backend viz  
- **Researcher:** Fit slug→`x.seed` / `li.google_site` query list when ready  
- **DA:** this file is the scoring/telemetry source of truth; amend only with gate changes

---

## 8. scout_run.query_or_slug examples (wired 2026-09-09)

**Seed source of truth:** [`fit-query-seeds.md`](fit-query-seeds.md)  
**Weekly priority:** `sca-nonweird` → `cvp-measurement-layer` → `gpt4o-weird` first; `cheap-gen-scarce-verify` when Adepa/carta live.  
**Anti-seeds:** no Loop Pilot / Perwell / pricing queries.

### Example ScoutRun payloads
```json
{
  "scout_run_id": "ex-x-seed-001",
  "adapter": "x.seed",
  "query_or_slug": "sca-nonweird",
  "query": "LLM synthetic subjects WEIRD",
  "candidates_n": 0,
  "events": []
}
```
```json
{
  "scout_run_id": "ex-li-google-001",
  "adapter": "li.google_site",
  "query_or_slug": "cvp-measurement-layer",
  "query": "site:linkedin.com/posts \"construct validity\" LLM OR \"Big Five\" LLM",
  "candidates_n": 0,
  "events": []
}
```
```json
{
  "scout_run_id": "ex-manual-001",
  "adapter": "manual.paste",
  "query_or_slug": null,
  "query": "https://x.com/.../status/...",
  "candidates_n": 1,
  "events": []
}
```

Scorer maps `query_or_slug` → Fit via `fit-tags.md`; empty / unknown slug → Fit = 0 → no enqueue.
