# Marketing Scouter — Linear Precision

Design stance for a command-driven dashboard used by one author (an economics PhD student) who writes well but never markets.

## Stance

**Linear Precision.** Dark, calm, exact. Background luminance steps elevate surfaces instead of drop shadows. Indigo is reserved for interactive elements only. Every word earns its place — no filler, no lorem ipsum, no emoji.

## Design tokens

| Role | Value |
|---|---|
| Page background | `#08090a` |
| Panel surface | `#0f1011` |
| Elevated surface | `#191a1b` |
| Primary text | `#f7f8f8` |
| Secondary text | `#d0d6e0` |
| Tertiary text | `#8a8f98` |
| Muted / meta | `#62666d` |
| Accent (indigo) | `#5e6ad2` / hover `#828fff` |
| Borders | White at 5–8% opacity |
| Radii | 6 px / 8 px / 12 px |
| Type | Inter (400, 510, 590) with `font-feature-settings: "cv01", "ss03"`; JetBrains Mono for labels and counts |

## Key choices

- **Surfaces lit by luminance, not shadows.** Depth from background tone steps (`#08090a` → `#0f1011` → `#191a1b`), not box shadows.
- **Workspace as full viewport expansion, not a modal.** Clicking a card expands its column context to fill the screen — the side rail keeps the source and relevance persistent.
- **Three distinct editors per panel type.** Op-eds get a word counter (200 cap) and language chip; trends get a character counter (1200 cap) with a preview card; commentary shows the thread context beside a reply box.
- **Liquid-glass hover.** Translucent surface layer with backdrop blur and a specular highlight that follows the cursor, revealing a short preview of the proposed post's angle.
- **Nothing leaves this app without you.** Printed permanently in the chrome — not a legal disclaimer, a design constraint.

## Trade-offs

- **Static data; no live fetch.** The Scout button shows a fake in-progress state and demo counts. A real backend would replace this.
- **Single-file simplicity.** All CSS and JS inline — no build step, but no component reuse either.
- **1440×900 target with 1100 px floor.** Not responsive beyond that breakpoint.
- **Google Fonts dependency for Inter.** Falls back to system-ui without the network fetch.

## Best for

Validating the interaction model — three-panel card layout, panel-specific editors, liquid-glass hover, and the linear precision design language — before committing to a backend build.