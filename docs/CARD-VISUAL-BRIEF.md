# CARD-VISUAL-BRIEF v0 (Designer, Oct 8 2026)
Scope: visual layer for web/ (Queue card, chrome, Handoff panel, Inventory, and the upcoming Watchlist / Done-Skipped views).
Hard rule: no behavior, copy, route, or data-testid changes. Locked copy ("Suggests only · Never posts" banner, footer invariants) stays verbatim. No Post/Schedule/publish affordance anywhere.

## 0. Guardrails (from SE / Adversarial / Marketing)
- All tokens live in ONE file: web/src/tokens.css (CSS custom properties). A lint/build check fails if any hex/rgb/hsl color appears outside tokens.css.
- vitest DoR checks stay keyed to data-testid, never to classes or colors.
- NEW Playwright visibility check against :5173 (headless, 1280x800 and 390x844): assert toBeVisible() plus a readable size (font-size >= 11px, box height > 0, not clipped by overflow) and WCAG AA contrast (>= 4.5:1 text) for:
  banner · all six s9-* factors (incl. EffortPenalty) · evidence label (soft_pending variant) · door badge (both doors) · selected-asset strip incl. sa-tone · likes-info.
- Soft/pending Evidence must never use the success (A) color token.

## 1. Tokens (tokens.css)
Color (warm neutral base, door is the only accent):
  --paper #F7F5F0   --surface #FFFFFF   --ink #1C1C1A   --ink-2 #55534E   --ink-3 #6E6B63 (AA on paper and white)
  --line #E4E0D7    --line-strong #CFCABE
  --door-econllm #2F4B9A  --door-econllm-tint #E9EDF8
  --door-civic   #9A4A15  --door-civic-tint   #FBEEE3
  --ev-a #2E6B3F --ev-a-tint #E3F1E6 · --ev-b #4A4F5C --ev-b-tint #ECEDF1 · --ev-soft #8A6400 --ev-soft-tint #FFF3CC (soft = hatched/dashed border, never green) · --ev-out #9B2C2C --ev-out-tint #FBE5E5
  --banner-bg #1C1C1A --banner-fg #FFFFFF (high contrast, always)
  --focus #2F4B9A
Type: --font-ui "Inter Tight", "Geist", system-ui; --font-mono "JetBrains Mono", ui-monospace (slugs, S, factor values, kill ids, counts).
  Scale: 11 / 12 / 13 / 15 / 18 / 22. Claim = 18/1.35 semibold. Nothing under 11px.
Space: 4px grid (4, 8, 12, 16, 24, 32). Radius: 8 card, 6 controls, 999 pills. Shadow: none on cards; 1px --line border. Elevation only for the sticky strip (0 1px 0 --line).
Motion: 150ms color/border only; no layout animation; honor prefers-reduced-motion.

## 2. Card anatomy (top to bottom), max width 720px
1. Meta row (12px, --ink-2): door badge (filled tint + door color text, plus a language cue "ES" on civic) · outlet · move · T status ... right-aligned S in mono 18px bold (S = 91.0).
2. Claim (18px semibold, --ink) with lang attribute. This is the biggest thing on the card.
3. Slug in mono 12px pill under the claim.
4. Asset line (13px): title · type/surface · tone_hint (normal weight, NOT italic fine print) · Evidence label. In scoped mode this sits directly under the claim and above the draft.
5. §9 strip: ONE compact row, all six factors always visible: label (11px, --ink-2) over value (13px mono) with a thin 3px bar showing 0..1 in --ink-3 (EffortPenalty bar uses --ev-out to read as a penalty). Six equal columns on desktop, 3x2 grid under 560px. An optional "Why" disclosure may add explanations below; it never hides factors.
6. likes-info (12px --ink-3, AA checked): "likes N · informational, not in S". No chip, no score styling.
7. Civic only: source chip (La Gaceta) + Draft preview (es) as a quote block with a 2px door-civic left rule.
8. Footer row: primary button "Copy handoff → x-brief" (ink bg, 36px tall, 44px tap target on mobile). Secondary actions as text buttons.
Door edge: 3px left border in the door color (keep), card background --surface, border --line.

Killed card: single compact row, mono kill id in --ev-out, reasons in --ink-2, 60% height of a live card, no draft/handoff.

## 3. Global chrome
- Banner: full-width, --banner-bg, 13px semibold, 40px tall, never collapsible or dismissible.
- Top bar: tabs (Queue / Watchlist / Done-Skipped / Wins / Inventory) as underline tabs, 15px; cap meters as mono pills "X 3/7 · LinkedIn 1/7" right-aligned.
- Selected asset strip: sticky under the top bar, --surface with bottom --line, 13px; title semibold; door badge; slug mono; tone_hint at full --ink-2 weight. Marketing gate: stays above any draft and fully readable.
- Door legend + footer invariants: 12px --ink-2, AA contrast.

## 4. Handoff panel / Inventory / tables
- Panel = same card shell, 16px padding, section labels 11px uppercase tracking .04em --ink-2.
- Closed-Fit interest list: two columns; paused items keep full text with a "Paused" pill and --ink-3 (not 50% opacity, which fails contrast).
- Receipt form: labeled inputs 36px, 1px --line-strong, focus ring 2px --focus.
- Inventory table: 13px, row height 36px, selected row --door tint of that asset, mono slugs, Evidence label component reused (soft stays amber).

## 5. Watchlist / Done-Skipped
Reuse the card at a "compact" density (meta row + claim + slug + S + status pill); expand to full anatomy on click. All six §9 factors still visible in expanded state; compact state shows S only and must label itself "S (6 factors)" so nothing is implied hidden.

## 6. Mobile (390px)
Single column, 16px gutters, sticky banner + selected-asset strip combined height <= 96px, §9 as 3x2 grid, primary button full width.
