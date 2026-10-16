# Market Scouter redesign session: experience side (Designer, 2026-10-10)
Systems Designer adds discovery sources, cuts, and build sequence. No code until Augusto agrees.

## Diagnosis in one line
It looks like a recommender but behaves like a manual paste classifier, and it splits one job across two tools. Augusto pasted a link, got "Not a fit", and never saw a draft. From his side, nothing happened.

## (a) The jobs, in Augusto's words
1. **"Show me where my work is relevant right now."** Find live conversations on X and LinkedIn where one of my papers, repos or essays genuinely adds something. I shouldn't have to go looking first.
2. **"Give me a reply worth posting."** A short draft in my voice that points to the right piece of work, ready for me to edit.
3. **"Keep me from looking bad."** Don't overclaim, keep my research voice and civic voice apart, keep me from spamming (7 a day per outlet), and never post for me.
4. **"Prove it's working."** A running record of replies I actually posted, tied to the work they promoted. It feeds my dossier.
5. (Occasional) **"Keep my list of work current."** Add a new paper or essay so it starts getting matched.
Not jobs: grading a post I already found, managing seals, checksums or lenses, or understanding two tools.

## (b) One flow, asset to Win. x-brief becomes a step inside it.
```
Scouter finds openings ─► Today feed ─► Open a card ─► Edit the draft ─► Copy & open on X
        ▲                                                                     │
  (assets = topics)                                                          ▼
                                     Win logged ◄── "Did you post it?" Yes ◄── back in app
```
1. **Assets are the setup, not a gate.** Each asset's topics drive discovery automatically. Promoting a single asset becomes a filter chip on Today ("All work · SCA paper · cvprofiles · …"), not a required first step.
2. **Openings arrive.** Discovery (Systems Designer's side) puts scored candidates into Today. Each card leads with **the post**: author, the text itself, how long ago, and a link. Then one sentence on **why it fits**: "Matches your SCA paper: synthetic agents beyond WEIRD samples."
3. **The draft is already there.** x-brief runs behind the card and the draft is pre-written when the card appears. If it's still drafting, the card says "Writing a draft…". If x-brief is down, the card says "Draft unavailable right now. You can still reply yourself", and the post and fit stay useful. The words "x-brief", handoff, seal, checksum and lens never appear in the UI. Sealing stays on the backend.
4. **Edit, then copy and open.** The draft is editable inline. One primary button, **"Copy reply & open on X"** (or LinkedIn), copies the edited text and opens the original post. Secondary actions: "Not for me" (with an optional reason, which trains ranking) and "Later".
5. **Confirm.** When he comes back, the card sits at the top under "Did you post it?" with **Yes, I posted it / Not yet / Skip**. Yes logs the Win. An optional "paste your reply link" field upgrades it to a verified Win.
6. **Wins.** A Wins page and a weekly count on Today ("3 replies posted this week · 2 on the SCA paper").

Manual check stays, but secondary: a "Check a post" box on Today for things he found himself. **If he pastes only a link, never score empty text.** Fetch the text read-only if discovery can, otherwise ask: "Paste the post's text too. I can't read X links on my own yet." Show "Not a fit" only after real text was scored, and give the reason in a sentence.

## (c) The home screen (Today) on open
Proactive, not a form. Top to bottom:
1. **Banner (locked, needs sign-off to reword):** I propose "Suggests only. You post everything yourself." The current "x-brief owns thought → revise" line meant nothing to him. Adversarial and Marketing need to agree before the locked copy changes.
2. **Status line:** "Updated 12 min ago · Finding new openings…" (live). If discovery or drafting is down, say so in words here, not as a grey dot.
3. **Waiting for you:** cards he copied but hasn't confirmed, with Yes/Not yet inline. Shown only when there are any.
4. **Openings:** ranked cards (post, why it fits, score, draft, actions). Filter chips: All work / each asset · X / LinkedIn. Budget shown in words: "4 of 7 X replies left today."
5. **Check a post:** a collapsed input at the bottom.
6. **This week:** a Wins count strip that links to Wins.

Empty states:
- First run, nothing discovered yet: "I'm looking for conversations about your work. First openings usually show up within the hour." Then show the asset topics it's watching, and "Check a post" as the thing to do now.
- Nothing new today: "No strong openings right now. Next check at 3:46 PM." No fake filler.

Navigation shrinks to **Today · Work (assets) · Wins**. Queue merges into Today, Scout becomes the Check box, and How it works stays as "?".

## Card anatomy v2 (changes from CARD-VISUAL)
Order: post (quoted, author, age, link) → why it fits (1 line + asset chip + door badge) → draft (editable) → actions → score row.
- The score becomes a word plus a number ("Strong · 91"). The six factors stay **visible by default** as one compact row under the score, at smaller weight. This keeps Adversarial's gate; it isn't hidden behind a disclosure.
- Evidence label and likes-as-info text stay.
- Civic cards stay English on X and LinkedIn; "ES · op-ed" appears only on op-ed cards.

## Plain-words map for the UI
Queue → Today · Scout → Check a post · handoff → (gone) · receipt → "Did you post it?" · no_lens → "No draft style for this topic yet" · empty_fit → "Not about any of your work" · door EconLLM / Augusto-civic → "Research voice" / "Civic voice" (badge colors kept) · cap → "replies left today".

## Decisions for Augusto (experience side)
1. Is "suggests, I post" still the line, or does he want one-click posting later? (The current invariant says never post. I'm assuming that holds.)
2. Approve rewording the locked banner.
3. How fresh does discovery need to be: hourly, or a morning and afternoon batch? This sets the status line and the empty-state promise.
4. Should "Not for me" reasons be collected? It's one optional tap, and it improves ranking.

## What must be true for him to feel it "works" (acceptance)
- Opening the app the next morning shows at least 3 real openings with drafts, with no setup step.
- From open to copied reply in 3 taps or fewer.
- A link-only paste never returns "Not a fit".
- No tool names or pipeline terms on screen.

---

## Systems side (Systems Designer)

### Where discovery comes from
The app has no X access (x-brief's API mode needs X developer approval that we don't have), so discovery runs outside the app and fills it:
1. **X discovery routine (new).** On a schedule I run read-only public X search with my own X access (no login as Augusto, can't post). For each active asset it searches the asset's topic phrases and claim terms, takes posts from the last 48h, and POSTs post text + author + URL into the scouter's existing scoring (`/scout`). Only passing cards are kept. Budget: at most 25 results per query and about 150 reads per run, well under the 1000/day limit.
2. **Pre-drafting.** For every new card that passes, the same run calls the x-brief bridge, so the card arrives with a draft already written. Drafts are made by the routine, never on page open. Cards whose draft fails or is blocked by the gate show "Draft needs your edit", not a blank.
3. **Feeds.** arXiv (author/topic queries) and Substack RSS refresh "Work" (Augusto's own assets) daily, so the asset list stays current with no typing. This is a suggestion only; a new asset is added only when he taps Add.
4. **Link-only paste (Check box).** The app tries to fetch public post text for an X link. If it can't, it says "Couldn't read that post. Paste its text." It never scores an empty text again (with a test).

### Cadence and freshness
- Discovery: weekdays 8:15am, 12:15pm and 5:15pm PT. First run right after approval, so "first openings within the hour" is true.
- `/status` returns `last_discovery_at`, `cards_added`, `drafts_ok` / `drafts_failed`, and x-brief health in words. The status line reads e.g. "Checked X 2h ago · 6 new openings · drafting works".

### Cut or hide
Handoff/seal/receipt language, the separate "paste into x-brief" step, the Assets gate, and the asset picker as a required first step. The internals stay (TTL, attested receipt, hash chain); only the words go. "Did you post it?" → Yes + public link = Win (evidence rules unchanged).

### Build order (after Augusto approves)
1. Fix link-only scoring + `/status` freshness (small, ships first).
2. Discovery routine + pre-drafting into the existing queue.
3. Today feed + 3-tab nav per Designer.
4. Work feeds (arXiv/Substack).
5. Only then: GC tuning, advanced search.
Every slice is done only when it works end to end on the live app at both screen sizes and Augusto can complete one opening → copied reply → Win with no help.

### Open risks
- Read-only X search quality: precision might be low. We measure the share of discovered cards that Augusto drafts vs. skips in week 1.
- x-brief `process` drafts its whole pool, so pre-drafting costs scale. We cap at 10 drafts per run.
