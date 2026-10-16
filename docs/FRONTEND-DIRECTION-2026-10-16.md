# Market Scouter frontend direction (2026-10-16)
The aim is a calm editorial triage desk. It should feel like a well-set newspaper inbox, not a dashboard. Speed comes from keyboard triage and instant optimistic state, not from animation.

## Type
- **Inter Tight** (already bundled) for UI. Scale: 13 / 15 / 17 / 22 / 28, with line-height 1.45 for body and 1.2 for headings.
- **JetBrains Mono** only for numbers: the score, the factors and the budgets. Never use it in sentences; that's what caused the status-line wrap.
- Quoted posts at 17/1.5 in ink-1. The post is the hero of each card, so it gets the largest text on the card.
- Optional editorial accent: **Newsreader** italic for the empty-state and Wins headlines only.

## Color (tokens.css; keep the AA-checked values)
- Paper #F7F5F0, card #FFFFFF, ink-1 #1A1917, ink-2 #45433E, ink-3 #6E6B63, rule #E6E2D9.
- Voice colors are the only hues: Research #2F4FA8 and Civic #9A4A15, used as a 3px left rule on the card plus the badge.
- Evidence states: A is a green outline. B·pending is a dashed ochre outline with #7A5A00 text on #FBF3D9 (re-check AA). C never appears on Today.
- One accent action color, ink-1 black, for the primary button. Never use a gradient.

## Card anatomy (top to bottom)
1. Source row: avatar 20px · @handle · age · platform icon. "Open post" is the whole quote block (clickable), not a separate link.
2. **Quoted post**: 2–4 lines with a fade, and "more" expands it in place.
3. Why it fits (one sentence, human labels): "Matches your Adepa carta: cheap generation, scarce local verification."
4. **The suggestion** (see the pattern below).
5. Action row: primary · Not for me · Later. Keys J/K move between cards, C copies and opens, X dismisses, L sends to Later.
6. Score footer, collapsed by default to "Strong · 91 ▸". Expanding it shows the six factor bars. (Note: this conflicts with the Playwright default-visibility rule for the six factors. Augusto has to sign off before we change it; otherwise the factors stay visible as a compact 6-column strip, 11px labels and 2px bars.)
- Card padding 20 (16 on mobile), 12px gap between sections, radius 10, a 1px rule and no shadow. Hover lifts the border to ink-3, and nothing moves.

## Inline suggestion pattern (no chat)
- The draft reads as text with a soft paper-tint background and a "Suggested reply" label. It's not an empty-looking textarea. Clicking it makes it editable in place, and the border appears.
- Below it, 2–3 one-tap rewrite chips: "Shorter", "More direct", "Add the paper link". Tapping one replaces the text, briefly shows a strikethrough diff of what changed (600ms), and adds an Undo link for 8s. No conversation, no history panel.
- Accept is the primary button. Dismiss gives a reason chip row ("Off-topic", "Bad target", "Already said this"), one tap, optional, and the chips feed the ranker. The card collapses with a 180ms height+opacity transition and the next card slides up.
- Every state is visible: Drafting… (skeleton lines, not a spinner), Ready, Edited (a dot), Copied ✓ (a 2s toast with "Did you post it?" → Win).

## Today / Work / Wins
- **Today**: a single 680px column, a sticky solid-paper header (banner + tabs + status), and filter chips that scroll away. Order: Openings → Saved for later (collapsed) → Wins strip.
- **Work**: a table on desktop and stacked cards on mobile. Slug pills wrap with row-gap 6, and the chips are nowrap. Each asset row's "Show on Today" control becomes an inline count ("3 openings ▸").
- **Wins**: a vertical timeline with the date, the post link, the reply excerpt, and a "Mark result" control (likes, replies or follow-on) entered by hand. The empty state is one sentence in Newsreader italic.

## Motion (GSAP or CSS, 150–220ms, ease out-quart; honour prefers-reduced-motion)
- Card enter: 8px rise plus fade, staggered 40ms, only on the first load.
- Dismiss and accept: collapse plus a next-card slide (FLIP).
- Score count-up only the first time a card appears (400ms).
- Nothing loops, nothing floats, and there's no hover tilt.

## react-bits: what to use and what to skip
Worth using (sparingly):
- **AnimatedList**: the card-entry and collapse choreography, or copy its pattern into GSAP.
- **CountUp**: the score number on first appearance.
- **FadeContent / AnimatedContent**: section reveals on Wins.
- **Stepper**: the 3-step first-run guide on Work.
Skip these as slop: Aurora, Particles, Silk, Squares/Waves backgrounds, ShinyText, GradientText, BlurText/SplitText headlines, SpotlightCard, GlareHover, ClickSpark, Magnet, Dock, tilted cards. They're decoration that fights reading and makes it look like "AI SaaS".

## Shaders
At most, one static paper-grain noise overlay at 2–3% opacity on the page background (rendered once and cached as an image). No animated shaders, mesh gradients or WebGL backgrounds. They cost battery and time on mobile and add nothing to a reading tool. If that's not cheap, skip shaders entirely.

## References
- **Linear Inbox**: keyboard triage, quiet chrome, instant optimistic state.
- **Superhuman**: one item in focus, J/K, undo toasts, a split second between action and next item.
- **Readwise Reader**: editorial type and quote styling on a paper background.

## Remaining P2s (from Wednesday)
1. Make the sticky header block a solid paper background with a 1px bottom rule; the chips are not sticky on mobile.
2. Playwright AA failures: fix them in tokens.css and send me the selectors and ratios. The banner-to-status gap is 12px per the spec.
3. The meta row duplicates the voice next to the badge and has dangling dots at 390. Drop the duplicate and use gap instead of dot separators.
4. Work: the slug pills overflow their rows, and the Evidence B·pending chip wraps.
5. The guide has two dismiss buttons. Keep only "Got it, show Today".
6. Remove the footer jargon line ("likes never drive S · Fit empty → 0…"); it belongs in "How it works".
