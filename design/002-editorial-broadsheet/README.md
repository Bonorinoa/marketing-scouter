# Marketing Scouter — Editorial Broadsheet

## Design stance

A light, warm, printed-paper interface crossed with a research memo. Three-column dashboard for one author who reads foreign-language and English sources across three panels (op-eds, trends, commentary) and writes proposed replies that never leave the app automatically.

## Key choices

- **Palette**: cream paper (`#f6f0e4`) and deeper sand (`#e8dcc3`) as the page, oxblood (`#6b1e23`) for active states and rules, muted brown (`#7a6a58`) for metadata. Ink-black (`#1d1a16`) for body text.
- **Type**: Georgia/Times New Roman for headlines and body; Helvetica Neue / Arial in `font-variant: small-caps` for labels, counters, and metadata.
- **Structure**: Masthead with date and issue number, double hairline rules between sections, column headers as `01 Op‑eds` / `02 Trends` / `03 Commentary`, zebra-striped alt-lens tables, quiet footer line.
- **Liquid glass**: Cursor-following warm specular highlight (oxblood-tinted) over a frosted translucent overlay that reveals a short preview of the proposed post. Stays cream-warm, never dark-mode.
- **Workspace**: Two-page spread — source on the left folio, editor on the right. Three distinct editor chrome panels (letter editor with word counter + language chip, post composer with char counter + preview card, reply box with thread context on the left page).
- **Data**: All 20 real items and the sample draft embedded inline — no external fetch, no invented headlines.
- **Privacy**: Chip shown when `personal_flag > 0.3`. Permanent footer: *Nothing leaves this app without you.*

## Trade-offs

- Single-file HTML with all data inline is large (~50 KB) but portable — opens directly in any browser.
- Static demo uses fake Scout delay and clipboard fallback; real backend would replace the embedded data and wire the Draft endpoint.
- Google Fonts not used (Source Serif 4 unavailable); the Georgia stack renders reliably on every OS.
- Hover glass effect uses JS mousemove on each card — fine at 20 cards, would need `will-change: transform` care at scale.

## Best for

- Visual sanity-checking the Editorial Broadsheet concept before any backend work
- Stakeholder review of the three-panel workspace variants
- Copy-editing the Spanish items and verifying counter logic (200-word cap, 1200-char cap)
- Testing the privacy-chip threshold against real `personal_flag` values