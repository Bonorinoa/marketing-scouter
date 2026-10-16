# Sheets win-export schema (personal O-1A dossier)

**Owner:** Augusto personal — **no `org_id`**.  
**Consumers:** Marketing (dossier) · Systems (Streamlit export button).  
**Source:** `ScoutEvent` rows with `kind=win` via `src.win_export.aggregate_wins`.

## Columns (fixed order)

| Column | Type | Notes |
|--------|------|--------|
| `date` | ISO date `YYYY-MM-DD` | from event `ts` (UTC date) |
| `slug` | string | **MUST** be filled from the acted card at emit; primary Fit claim slug (e.g. `sca-nonweird`, `verification-local-context`) |
| `outlet` | `x` \| `linkedin` | **MUST** be filled from the acted card at emit; where the win happened |
| `asset_id` | string? | piece-keys the O-1A row when recommend was **asset-scoped**; omit / `null` only in explicit general / profile-wide mode (no asset on the card). Never invent; never borrow another piece’s id |
| `source_id` | string? | optional watchlist / press source id |
| `win_type` | enum | `claim_named_reply` \| `warm_intro` \| `evidence_ab` |
| `card_id` | string | ScoredCard id that produced the win |
| `note` | string | free-text human note |
| `evidence_url` | https URL | **required** to confirm a Win; public https link to the reply / intro / citation. Refused (422 `evidence_url_invalid` + `reason`): non-https, userinfo, localhost/loopback/private/link-local/IPv6 private IPs (incl. decimal/hex forms), the scouter itself (ports 8710/5173 on local hosts, `MS_APP_HOSTS`). At confirm time the host is resolved (injectable resolver, `getaddrinfo` default; no redirect following): any private/loopback/link-local address → `evidence_url_invalid` reason `resolves_private`; resolution failure → `evidence_url_unresolvable`. A provided `archive_url` gets the same check (`archive_url_invalid` / `archive_url_unresolvable`). Missing → 422 `evidence_url_required` |
| `archive_url` | URL? | Wayback snapshot; default `https://web.archive.org/save/<evidence_url>` or a provided link. `null` when archiving failed (event carries `archive_status=failed`; the Win is still recorded) |
| `criterion_hint` | enum | Closed list loaded from Researcher's `data/criterion_hints.json` (`values` keys, source of truth): `original_contribution` \| `published_about` \| `scholarly_authorship` \| `judging` \| `none`. When a confirm sends no hint, the default comes from `default_by_win_type`: `claim_named_reply`→`original_contribution`, `warm_intro`→`none`, `evidence_ab`→`scholarly_authorship`. Anything else → 422 `bad_criterion_hint`. A hint only; the lawyer decides |
| `is_test` | bool | test/fixture rows; excluded from `/wins` and export by default (`?include_test=true` to see) |
| `prev_hash` | sha256 hex | previous row's `row_hash`; first row `GENESIS` |
| `row_hash` | sha256 hex | sha256 of canonical JSON (sorted keys, no spaces) of all columns above + `prev_hash` |

## Python API

```python
from src.win_export import WIN_SHEET_COLUMNS, aggregate_wins

rows = aggregate_wins(events, cards_by_id=cards_by_id)
# write rows to Sheets / CSV in that column order
```

## Rules

- One sheet row **per** win signal (an event with two wins → two rows).
- Do **not** export Buffer %, Feed SR %, likes, or invented ER as win metrics.
- Distribution wins only (named reply / warm intro / Evidence A·B on acted cards).
- Emit `slug`, `outlet`, and `asset_id` from the acted card; `slug` is the primary Fit claim, `outlet` is `x` or `linkedin`, and `asset_id` piece-keys scoped Wins for O-1A. Legacy rows may be backfilled by `aggregate_wins(..., cards_by_id=...)`.
- Dossier is **Augusto personal** — no `org_id` column, ever.

## Evidence integrity

- The hash chain is **tamper-evident on this computer only**: it catches accidental edits, deletions and reordering of the log. It is **not tamper-proof** — anyone who can edit the log can recompute every hash — unless the head hash is anchored off-box (Sheet column / EOD email) and compared.

- Chain covers every Win in log order (test rows included). `GET /wins/verify` → `{ok, count, head}` or the first broken index; `GET /wins/head` → latest hash to anchor off-box (Sheet column / EOD email). Nothing is sent by the API.
- Test handoffs listed in `data/db/test_handoffs.json` (and anything under `MS_TEST_MODE=1`) refuse a Win with 409 `test_handoff_no_win`; skipping is allowed.
- `POST /wins/export/sheets` stops and logs `sheets_export_blocked: Google sign-in missing` until Augusto's Google connection exists (`MS_GOOGLE_SHEETS_CONNECTION`). Never crashes.
- Live archiving (Wayback) runs only on a real attested confirm; tests set `MS_ARCHIVER=off`.
