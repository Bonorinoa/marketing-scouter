# Tab purpose + empty-state copy (Researcher)

Plain words. No promise to post. No score shown without data.

| Tab | One-line purpose | Empty state |
|---|---|---|
| Scout | Paste a post or thread URL and see whether it fits the asset you're promoting. | Nothing scouted yet. Paste a link from X, LinkedIn, or Substack to score it against the selected asset. |
| Queue | Your best openings right now, up to seven, ranked by fit. | No openings yet. Scout a few links, and the ones that fit your asset and have solid evidence will show up here. |
| Handoff | Cards ready to send to x-brief for drafting. You write and post; the app never does. | Nothing waiting for x-brief. Pick a card in the Queue and choose Hand off. |
| Wins | Exposure you confirmed actually happened, by asset and outlet. | No wins logged yet. A win counts only after you confirm the receipt. |
| Assets | The pieces you're promoting: papers, repos, essays, cartas. | No assets yet. Add one with its surface, tone, and door so recommendations can be scoped to it. |
| Watchlist | Sources worth checking often, including Tucumán/NOA civic outlets. | No sources yet. Add a feed or account to check on a schedule. |
| Done/Skipped | Cards you acted on or set aside, with the reason. Expired handoffs are listed separately. | Nothing here yet. Cards you finish or skip move here. |

Killed card (stays on screen): "Not a fit: {reason}. Nothing was queued."

## Add asset form: closed vocab (DA's required fields)
- surface: arxiv · github · medium · carta · lab · conference · working_paper · substack (pick list, no free text)
- door: EconLLM · Augusto-civic (pick one, required)
- tone_hint: short free text, required. Hint: "How should drafts sound? e.g. rigorous-plain, civic English on X, Spanish for op-eds"
- Fit slugs: chips from fit-tags.md only

## Redesign tabs (Oct 13)
| Tab | Purpose | Empty state |
|---|---|---|
| Today | A few conversations where one of your pieces has something real to add. | Nothing worth your time right now. New posts are checked a few times a day. |
| Work | Drafts you're shaping. You edit and post them yourself. | No drafts in progress. Open a conversation from Today to start one. |
| Wins | Times someone engaged with your ideas, each with a public link. | No wins yet. A win counts only after you confirm it with a link. |

## Promotional chip (Oct 13, either mode; API label brand_post)
- Chip: **Promotional**
- Tooltip: "From a company account, or carries a product link or sign-up pitch. No draft prepared; reply only if it's worth it to you."
- Label only; does not change S or the queue.

## Rank line (Oct 13, claim-first ordering)
- Claim tier: "Ranked first: argues one of your claims · S {S}"
- Topic tier: "On your topic, no claim to answer · S {S}"
- Tooltip: "Cards that argue a claim you've made come before topic cards. Within each group, higher S ranks higher."

## Language cap (X only; never on op-ed or Tucumán/NOA cards)
- Chip: "Not clearly English"
- Tooltip: "Your X account is English-only. This text isn't clearly English, so it gets no claim draft. Ranked as a topic card."
- Trace line: "Language: {lang} · capped at topic ({reason})" where reason is `lang_capped` or `non_latin_script`.

## Drafter decline (X claim cards)
- Card line: "No draft: the drafter passed on this one. Reason: {reason}"
- Tooltip: "The drafter read this and chose not to reply. You can still reply yourself from the handoff."
- {reason} is the cleaned text (no links or handles, max 140 characters); empty reads "none given".

## Template cards (no draft)
- Card line: "No draft: the basic drafter can only repeat your claim, so this one is left blank."

## Copy with caveat (secondary button; main copy never includes the caveat)
- Tooltip: "Copies the draft with the caveat as its last line. Whether readers see the caveat is your call."
