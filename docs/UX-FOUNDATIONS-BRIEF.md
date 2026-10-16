# UX-FOUNDATIONS-BRIEF v0 (Designer, Oct 8 2026)
Trigger: Augusto's hands-on test: "looking nice, but the UX is quite poor (hard to use, know when the system is working, and what features it provides)."
Builds on CARD-VISUAL-BRIEF (tokens, card anatomy). Same guardrails: keep every data-testid, locked banner + footer copy verbatim, no Post/Schedule/publish affordance or verb, Playwright visibility checks extend to every new element below. New elements get new test ids (listed).

## 0. What's wrong today (from App.tsx + 1280x800 screenshot)
1. No feedback: Scout, Copy handoff, receipt and refresh have no pending state; results and errors arrive as raw JSON in a <pre> (`setMsg(JSON.stringify(...))`). Nothing tells you the API is up.
2. No story: the app opens on an Inventory table. The loop (pick asset > paste a post > get a card > hand off to x-brief > confirm you shared it > Win) is never stated.
3. Jargon is the UI: "S", "T=ok", "door", "claim-source label (not org ownership)", "FormatPrior", "decision: enqueue", "kill: door_mix". Engineers' names, not Augusto's.
4. Two ways to select an asset (dropdown AND row click) and the selection silently changes Queue.
5. Possible scope bug to verify: in the screenshot the Selected asset strip says Adepa / La Gaceta (scoped), yet the Queue shows the SCA EconLLM card too. Either the strip is stale or Queue isn't scoped. Fix or label it.

## 1. Information architecture
Rename + reorder tabs to follow the loop, numbered so the order is obvious:
  1 Assets  ·  2 Scout  ·  3 Queue (n)  ·  4 Wins (n)          [right side: API status dot · X 2/7 · LinkedIn 0/7]
- Default view: Queue if it has cards, otherwise Scout; first run shows the guide (section 3).
- Count badges on Queue and Wins (test ids: nav-count-queue, nav-count-wins).
- ONE asset picker: a compact "Promoting: [asset ▾]" control in the selected-asset strip, visible on every tab. Assets tab rows get a "Promote this" text button that sets it. Remove the duplicate <select> on the Assets tab. Changing it shows a toast "Now scouting for: <title>. Queue filtered."
- Watchlist and Done/Skipped (later) go under Queue as filter chips (Open · Watching · Done · Skipped), not new top-level tabs.

## 2. Status & feedback patterns (one system, used everywhere)
- API health dot (test id: api-status) in the top bar: green "Connected", amber "Slow" (>2s), red "Offline: start the API on :8710". Poll /health (or /openapi.json HEAD) every 15s; when red, disable action buttons with a tooltip saying why.
- Button pending: label swaps to a verb-ing form + inline spinner, button disabled, min 300ms so it doesn't flicker: Scout > "Scouting…", Copy handoff > "Sealing…", Confirm > "Recording…". (test id: btn-pending on the busy button)
- Result toasts (test id: toast), bottom-center, 4s, also announced via aria-live="polite":
  success: "Card added to Queue (S 91)." · "Handoff copied. Paste it into x-brief." · "Win recorded."
  error: human sentence + "Details" disclosure holding the raw JSON. Never show raw JSON by default.
- Inline outcome panel under the Scout form (test id: scout-outcome) for the four outcomes, each with one clear next step:
  enqueued: show the card + "View in Queue"
  killed: "Not a fit for <asset>: <reason in words>." + secondary "Why?" (kill id in mono inside)
  asset_pick_required: "This post fits more than one of your assets. Which one are you promoting?" + asset buttons
  replaced: "Added. It bumped a weaker card (S 72 → 91)."
- Skeleton rows for Queue/Assets/Wins while loading (test id: skeleton) instead of blank space.

Kill-reason plain-language map (keep codes in the Details):
  empty_fit > "Doesn't touch any topic this asset covers."
  door_mix > "Mixes your EconLLM and civic voices. Pick one asset first."
  cap > "You've hit today's 7 for this outlet."
  evidence_out > "Evidence too weak to recommend."
  expired_handoff > "This handoff expired after 72h. Re-scout to get a fresh one."
  (others: write one sentence each; default "Scouter skipped this: <code>.")

## 3. First-run guide (test id: onboarding)
Shown on first load (localStorage flag), reopenable from a "How it works" link in the top bar. Three short steps in one dismissible panel above the content, not a modal:
  Title: "Find the right conversations for your work."
  1. "Pick what you're promoting." A paper, repo, essay or carta from Assets.
  2. "Paste a post you saw." Scouter scores whether replying with that asset is worth it.
  3. "Hand off the best ones to x-brief." You write and share it yourself, then confirm here to log a Win.
  Footer line (locked spirit): "Scouter suggests only. It never posts for you."
  Buttons: primary "Start: pick an asset" (goes to Assets) · text "Got it".

## 4. Tab purpose lines + empty states
Each tab opens with a one-line purpose (13px, ink-2; test id: tab-purpose) and a real empty state (test id: empty-state) with one action.
- Assets: purpose "What you can promote. Each has its own topics, voice and evidence level."
  empty: "No assets yet. Add them to data/seed_inventory.json and restart the API." (no in-app add until there's an API route)
- Scout: purpose "Paste a post or thread. Scouter checks it against the asset you're promoting."
  empty (no asset picked): "Scouting across all your topics. Pick an asset for sharper matches." [Pick asset]
  form labels: "Post URL", "Post text (paste the thread)", "Where it's posted: X / LinkedIn". Placeholder examples, not "snippet".
- Queue: purpose "Best replies to make, highest score first. Up to 7 per outlet."
  empty: "Nothing queued for <asset>. Scout a post to fill it." [Go to Scout]
- Wins: purpose "Replies you actually shared, confirmed by you. These feed your dossier."
  empty: "No Wins yet. After you share a handoff, confirm it in the handoff panel to log one."

## 5. Vocabulary pass (UI copy only; API fields, test ids, data unchanged)
  S = 91.0 > "Score 91" (mono number, label "Score"; tooltip lists the 6 factors)
  T=ok > drop from card, or "Fresh" pill when ok / "Stale" when not
  door EconLLM / Augusto-civic > keep the badge text (Marketing gate) but legend reads: "EconLLM = research voice · Augusto-civic = civic Spanish voice"
  "claim-source label (not org ownership)" > move to the legend tooltip
  FormatPrior > "Format fit"; DoorMatch > "Voice match"; EffortPenalty > "Effort cost" (keep visible, Adversarial gate)
  "likes 900: informational, not in S" > "900 likes (not used in score)"
  "Copy handoff → x-brief" stays (it's the core action); after success the button reads "Copied ✓" for 2s.
  decision: enqueue > handled by the outcome panel.

## 6. Handoff + receipt flow
- Handoff panel opens as a right-side drawer on desktop / bottom sheet on mobile with a 3-step header: Copied > Shared in x-brief? > Confirmed.
- Receipt form asks one plain question: "Did you share a reply based on this?" Yes, I shared it / Not yet / Skip this card. Lens and win_type become a second, optional step. Attestation checkbox text: "I confirm I posted this myself."
- Pending handoffs show an "Awaiting confirmation · expires in 3d" pill on their Queue card so nothing is lost.

## 7. Done criteria for the slice
- Every action shows pending > success|error with a toast; no raw JSON visible by default (Playwright: no <pre> visible after a Scout).
- api-status visible and accurate (kill the API in test > red + disabled buttons).
- onboarding, tab-purpose x4, empty-state x4 visible at 1280x800 and 390x844.
- All previous DoR strips stay green; screenshots of each tab in both sizes in reports/.
