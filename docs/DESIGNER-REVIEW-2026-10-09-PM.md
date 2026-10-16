# Designer review: 2026-10-09 PM build
Reviewed: views-queue-waiting 1280, views-queue 390, views-handoff 390, views-add-asset 1280. Big progress: 88px mobile header, no_lens disabled state, radios, sealed line all landed.

## P1 (fix next run)
1. Civic X cards are still Spanish AND carry "ES · op-ed" while the meta row says "X · reply". That contradicts the English-only X rule. Civic X/LinkedIn cards = English claim + English draft, no ES chip. "ES · op-ed" only when outlet/move is an op-ed.
2. Both civic cards show the identical Spanish draft text under different claims. Looks like a draft-template/cache bug; each card's draft must derive from its own claim.
3. Add asset → Topics: checkbox chips are broken (large empty squares floating above labels inside oval outlines). Make them toggle chips: one pill per topic, 32px tall, label inside, checked = door-tint fill + check glyph, keyboard toggle with Space, wrap in a fieldset with legend "Topics (pick at least one)".

## P2
4. Toast while the handoff drawer/sheet is open: suppress the toast and show the confirmation inline in the drawer (the "Copied" step turns solid + "Copied ✓" on the button for 2s). Toasts only when no drawer is open, bottom-center.
5. Mobile sheet radios: rows are ~60px apart. Use a fieldset with 44px rows, 4px gap, the whole row tappable, 1px divider between options. Move "I confirm I shared this myself" directly under "Yes, I shared it" and show it only when Yes is selected.
6. Card in "Awaiting confirmation" still shows an active "Copy handoff → x-brief" button. Swap the primary to "Confirm or skip" (opens the drawer at the receipt step); keep re-copy as a text link.
7. Mobile: the no_lens reason ("x-brief has no lens for this topic yet.") renders below/outside the card. Keep it inside, directly under the disabled button.

## P3
8. Assets table: show human Kind labels (working_paper → Working paper, conference → Conference paper, github → Repo, medium → Essay, arxiv → arXiv paper, carta → Carta, lab → Lab). "Promote this" wraps to two lines: white-space: nowrap, or make it a small outlined button.
9. Asset subtitles still show raw tone_hint strings ("EconLLM methods draft — use lightly", "Augusto-civic Spanish / soft Evidence if pending"). Map through the same short label map as the card ("Methods draft", "Civic voice"); the "Spanish" wording is now wrong for civic.
10. Add asset form floats under the table with no container. Put it in a bordered panel (same shell as cards) with a title "Add an asset", max-width 560px, and selects for Where/Voice as segmented controls if ≤4 options.
11. Mobile tab labels look ~11px. Keep 13px minimum; if the row overflows, drop the numerals ("Assets · Scout · Queue · Wins") on <400px.

Footer: fine to keep the locked line now that How it works carries the plain version.
