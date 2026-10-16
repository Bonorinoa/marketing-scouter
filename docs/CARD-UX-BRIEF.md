# Card UX brief — Market Scouter (web shell)

**Owner:** Marketing (co-owned with Systems for shell IA)  
**Status:** locked for the continuous web-app build routine  
**Product gate:** suggests-only · never posts / schedules / OAuth-as-poster  
**Compose:** Scouter finds opportunities; x-brief (Mac) owns thought → revise → you post

Streamlit is a dead PoC. This brief is the IA contract for the real local web shell.

---

## Surfaces

1. **Inventory** — assets to advertise (arXiv paper / Substack / GitHub repo / carta / …) with Fit slugs, door, tone, purpose
2. **Watchlist** — topic sources (SERP / RSS / paste adapters)
3. **Queue** — scored cards, **cap 7 per outlet** (X / LinkedIn); scoped by selected asset or profile-wide
4. **Paste & Scout** — URL → Candidate → gates → card or kill
5. **Done / Skipped** — acted / edited / skipped history
6. **Wins** — O-1A dossier rows only (no vanity ER / Buffer % / impressions)

Search + scored recommend live on Inventory (asset selector) → Watchlist → Queue. Garbage collector owns expire / dedupe / kill retention (see GC below).

---

## Asset-scoped recommend (locked)

Each Inventory asset carries a different **tone and purpose** (e.g. arXiv paper ≠ Substack essay ≠ GitHub README ≠ Adepa carta). Recommendations are conditional on that asset.

| Mode | When | Behavior |
|------|------|----------|
| **Scoped** | User selects one Inventory asset | Fit + FormatPrior + draft tone keyed to *that* asset; Queue + handoff carry `asset_id`; claim one-liner from the asset’s Fit slugs |
| **General** | No asset selected | Profile-wide discovery across Active Fit / `fit-query-seeds.md` — still **closed vocab**, still scored Queue only after ≥1 Fit slug; never invent topics |

Rules:

1. Asset selector sits on Inventory (and is sticky on Queue / Paste & Scout until cleared).
2. Scoped Queue chrome shows **Selected asset:** title · type (arxiv|substack|github|carta|…) · door · primary slug.
3. Empty selection is explicit UI (“All interests”) — not a silent default that pretends to be scoped.
4. Handoff / Wins include `asset_id` when scoped so O-1A rows stay piece-keyed, not only slug-keyed.
5. Tone mismatch (e.g. civic Spanish carta while an English SCA paper is selected) → `door_mix` / refuse handoff — same brand gate as dual-door soft slugs.

---

## Global chrome (every view)

- Persistent **Suggests only · Never posts** banner
- Cap meters: `Open X n/7` · `Open LinkedIn n/7`
- Door legend: `EconLLM` = claim-source label (not org ownership); `Augusto-civic` = provincial / verification lane
- Footer invariants: likes never drive S · Fit empty → 0 → no card · Evidence C out · cap 7/outlet

**Forbidden affordances:** Post, Schedule, Auto-publish, “Connect X/LinkedIn as poster.”

---

## Scoring chrome (honest)

Show the **full §9 strip** on every scored card:

| Factor | Notes |
|--------|--------|
| Fit | empty → 0 → kill (`empty_fit`) |
| Urgency | age / reply heat |
| FormatPrior | reply / interject preferred |
| Evidence | A/B only for hard enqueue; **pending soft** (Adepa) — never A-green from a weak Jev flag |
| DoorMatch | one door only |
| EffortPenalty | shown, never hidden |

- **Likes** = informational only — never a score chip
- Kill cards show **kill id** before any draft or handoff exists: `promo_cta` · `empty_fit` · `evidence_c` · `door_mix` (+ folklore eligibility kills)

Formula reference (DA):  
`S = 30·Fit + 20·Urgency + 15·FormatPrior + 20·Evidence + 15·DoorMatch − EffortPenalty`

---

## Card anatomy

```
┌─────────────────────────────────────────────────────────┐
│ [DOOR BADGE]  outlet · format · T=ok|…                  │
│ Claim slug                          S = ##.#            │
│ Claim one-liner (primary copy)                          │
│ Asset (required when scoped) · type · Evidence · oped?  │
│ §9 strip: Fit Urgency FormatPrior Evidence DoorMatch EP │
│ [civic] outlet chip: La Gaceta | Contexto               │
│ Draft preview (secondary; Spanish if Augusto-civic)     │
│ Primary: Copy handoff → x-brief                         │
│ Secondary: Acted · Edited · Skipped                     │
└─────────────────────────────────────────────────────────┘
```

Rules:

1. **Named claim** (slug + one-liner) is primary; draft is secondary
2. **Matched asset** is required chrome in scoped mode (`asset_id` + type); general mode shows “profile-wide”
3. **One door badge** per card — never both EconLLM and Augusto-civic
4. **Augusto-civic** defaults Spanish (claim + draft preview); English-first is a bug
5. Civic cards show provincial **source chip** (`La Gaceta` / `Contexto`) so Wins can count press texture separate from X/LI
6. Primary CTA copies closed Fit handoff (below) — never “Publish”

---

## Card states

| State | Shows | Primary action |
|-------|--------|----------------|
| **Killed** | Kill id only — no draft, no handoff | Dismiss |
| **Enqueue** | Full card anatomy | Copy handoff → x-brief |
| **Replace** | Same + “bumped card X (ΔS ≥ 10)” | Same |
| **Handed-off** | Payload sealed; awaiting return | Acted / Edited / Skipped |
| **lens_mismatch** | x-brief confirmed lens ≠ Scout slug — Fit remains source of truth | Keep Scout slug on Wins |
| **Win** | slug + outlet (+ civic chip) · win_type | Sheets export |

Replace rule: enqueue/replace under cap-7 if `S_new ≥ min_open + 10`.

---

## Handoff → x-brief (closed Fit)

Payload must include:

- `url`
- matched Fit slug(s)
- `door` (exactly one)
- claim one-liner
- Evidence grade (+ `oped_status` when Adepa/carta)
- `interest_seed_closed: true`
- `asset_id` (+ asset type) when recommend was asset-scoped; omit only in explicit general/profile-wide mode

Integrity:

1. Seed x-brief Active interests **only** from `fit-tags.md` (see `data/xbrief-interests-seed.md`) — never free-form
2. Jev may **rank within** that set; weak support → flag / write with none — **not** a new claim id
3. **One door per handoff:** civic paste pauses EconLLM Active interests (Jev cannot abstain; English SCA “best+weak” must not land on Spanish civic)
4. If confirmed lens ≠ Scout slug → `lens_mismatch` ScoutEvent; Wins stay **slug-keyed** to Scout Fit
5. Adepa / `oped_status: pending` stays soft — weak lens must not upgrade Evidence to A

---

## Wins (O-1A dossier)

Countable only:

- `claim_named_reply`
- `warm_intro`
- `evidence_ab`

Columns: `date · slug · outlet · asset_id · source_id · win_type · card_id · note`  
Slug/outlet/`asset_id` filled from the acted card (never stuffed into `note`).  
No impressions / Buffer % / invented ER as success metrics.

---

## Garbage collector (UI expectations)

The GC is a product feature, not a silent cron. Surfaces should make retention legible:

| Action | Keep | Drop |
|--------|------|------|
| Dedupe | Canonical URL / status id | Duplicate candidates |
| Expire | Open cards past stale window → Done/Skipped with reason | Vanish without trail |
| Kill retain | Kill id + URL hash (audit) | Draft bodies for kills |
| Wins | Immutable without explicit retention policy | Auto-delete of win rows |
| Handoff orphans | Handed-off past hard TTL → terminal `expired_handoff` (not user Skipped) | Soft nudge / silent delete / fake Skipped |

Never GC a Win row without an explicit retention rule in the shell.

---

## Search & recommend (shell)

- **Asset first:** select Inventory asset → scoped recommend; clear selection → general profile search (closed Fit only)
- **Search:** asset_id, Fit slug, door, outlet, Evidence grade, kill id, Watchlist source, free-text over claim one-liners — vocabulary from `fit-query-seeds.md` + Watchlist, never free-form invent
- **Recommend:** scored Queue only — same §9 + S_safe; FormatPrior + draft tone follow selected asset when scoped; no folklore lifts; no auto-post
- Advanced automation = **more candidates into the scored queue**, not posting

---

## Voice seeds (Drafter preview only)

Scouter may show a door-shaped preview; authorship quality lives in x-brief.

- **EconLLM:** named research claim, no CTA  
- **Augusto-civic:** Spanish, verification-in-context, no CTA  
- One door per thread; never “DM me”

---

## Demo beats (unchanged)

1. Promo / bait → kill (`promo_cta`)
2. SCA / WEIRD → EconLLM enqueue + named claim
3. Gaceta / civic → Augusto-civic Spanish + soft Evidence if Adepa pending
4. Cap-7 replace → Acted → `claim_named_reply` on Wins

Voiceover: name `verification-local-context` for the civic lane even if `cheap-gen-scarce-verify` also shows on-card.

---

## Out of scope for this brief

- Merging x-brief into the web shell (compose only)
- macOS capture shortcut / Keychain (x-brief owns)
- Auto-post connectors (Postiz / Adspirer / Omneky — veto)
- Vanity growth metrics as success

---

## Brand-blocking before chrome

Adversarial + Marketing: ship before polish.

1. **`lens_mismatch` return path** — paste receipt / file drop / manual confirm from x-brief; without write-back the state is theater and Wins can lie.
2. **Door-scoped Active injection** — handoff must pause the other door’s interests (scripted `x-brief add` or refuse without pause checksum); clipboard `door` alone is not enough for civic Spanish.
3. **Dual-door soft slugs** — require explicit door on the card or `door_mix` kill.
4. **Handoff orphan TTL** — hard TTL + terminal action (force Skipped / quarantine), not soft nudge under cap-7.

5. **All-interests multi-match** — if one URL hits slugs from two assets with different doors/tones, force an asset pick (or take highest S among *asset-keyed* candidates with explicit chrome). Never silently merge doors.
6. **Receipt trust** — `POST /handoff/receipt` is user-attested only (paste/confirm). No silent clear of Handed-off; no Wins unlock from an unattended write.
7. **Orphan terminal = `expired_handoff`** — never auto-map TTL to user Skipped (Done/O-1A stats must not lie).


---

## Decision log

- 2026-10-09: Augusto's X account is English-only; Spanish is only for op-eds in Argentine newspapers. Civic X/LinkedIn cards are English; op-ed cards stay Spanish with an `ES · op-ed` chip. The Marketing check was updated to match, not loosened.

## Draft voice gate

`src/voice_gate.py` → `check_draft(draft_text, card) -> GateResult(ok, reasons=[{code, message}])`. Pure; never edits the draft; the UI shows `message` verbatim and keeps Augusto's edits. Runs on every x-brief draft before render and on every edit before "Copy final".

| Code | Rule |
|------|------|
| `lang_mismatch` | X / LinkedIn must be English (both doors); op-ed / carta must be Spanish (stopword heuristic, per 2026-10-09 decision). |
| `cta_bait` | No "DM me", "link in bio", "follow me", "subscribe", "check out my", "sign up" (+ Spanish: seguime, suscribite, escribime, link en bio…). One plain link, to the asset only. |
| `claim_missing` | Draft must share key terms with the matched slug's claim (fit-tags.md), the asset title or asset claim. |
| `door_mix` | Civic draft can't use "EconLLM", "our lab", "SCA pilots"; EconLLM draft can't pose as a civic op-ed/carta. |
| `too_long` | X ≤ 280 chars (each URL = 23); LinkedIn ≤ 3000. |
| `invented_metric` | No `N%` / `Nx` / `N times` / `N veces` unless N is in the card's claim text. |
| `empty_draft` | Empty draft. |
| `door_missing` | Card has no door, or an unknown one. Never defaulted. |
| `caveat_dropped` | The asset's `caveat` field must appear word for word in the draft (case and spacing ignored, after normalization). An Evidence B asset with no `caveat` field is blocked too: Grade B without its caveat is effectively Grade C. The drafter keeps claim + caveat and trims middle sentences only; if they still don't fit X, the draft is left as is and blocked `too_long`, never cut. UI label: "Caveat missing". |

All checks run on a normalized copy (NFKC folds math/roman-numeral lookalikes, zero-width chars removed, single letters with spaces/dots collapsed so `D.M. me` = `DM me`); the returned draft is untouched. Links include bare domains (`bit.ly/abc`, `example.com`; not `e.g.` or decimals). The one allowed link must equal the asset URL after normalization (scheme, lowercased host, path without trailing slash, query/fragment dropped); any `..`, extra segment or lookalike host is `cta_bait`. Query: only `utm_*` params, and only if the percent-decoded value carries no URL (`://`, `http`, `//`, `%2F%2F`, domain-like); any other param is `cta_bait`. A fragment is fine unless it carries a URL.

Engagement bait is `cta_bait` too: a sentence that starts with reply/comment/type/drop/like/RT/retweet/repost/share and then says "and I'll / I will / to get / for (the|my|a|access|more|free)"; Spanish: respondé/comentá/escribí/dejá … "y te (envío|mando|paso)" / "para recibir". Plain prose ("in reply to your point", "I like this for…") is not flagged.

**Warnings** (`GateResult.warnings`, shown to Augusto, never change `ok`):

| Code | When |
|------|------|
| `possible_metric` | Numbers in words: "forty percent", "doubling", "triple", "half as", "dos veces", "el doble", "cuarenta por ciento". |
| `claim_negated` | A negation (not, don't, doesn't, never, fail to, no, nunca…) within 3 words before a claim key term. |
| `lang_uncertain` | Draft too short to tell its language. |

`to_dict()` → `{"ok": bool, "reasons": [{code, message}], "warnings": [{code, message}]}`.
