# Marketing Scouter — Command Glass

## Design Stance

The most expressive liquid glassmorphism variant. The dashboard is a single surface where commands (not clicks) are the primary interaction metaphor — `/` or `Cmd+K` opens the command palette, and typed scout commands drive the workflow. Glass panels float over a slow aurora with specular highlights that follow the cursor. Restrained opacity keeps text readable.

## Key Choices

- **Dark graphite base (#0b0d10)** anchors the aurora layers
- **Three-panel hover accordion** — the hovered panel expands to ~56 % while the others become slim strips that keep their title and item count visible; expanded cards show their "proposed post" preview
- **Workspace replaces cards in situ** — clicking a card slides the panel into its editor (letter, post, or reply+thread) on the same glass surface, no modal
- **Per-panel editors** — op-eds get a letter editor with live word counter (200 cap) and language chip; trends get a post composer with character counter (1200) and preview card; commentary shows thread context alongside a reply box (200-word target)
- **Draft–review flow** — "Your take" captures the author's own angle; the Draft button (with a brief fake delay) fills the editor with the sample draft, shows a "Model suggestion" rationale, and surfaces a flags checklist
- **Privacy chip** appears when `personal_flag > 0.3` (all current items are below this threshold; logic is wired and ready)
- **Inter/Geist** via font stack (system fallbacks); tabular-numeric figures for scores
- **"Nothing leaves this app without you"** — fixed quiet line in the chrome, visible at all times

## Trade-offs

- Backdrop blur is GPU-heavy; older hardware may not render the glass effect smoothly
- Aurora animation respects `prefers-reduced-motion` but adds a rendering layer even when static
- Hover accordion disables when a workspace is open (two interaction modes cannot coexist)
- Only one glass layer deep avoids compounding blur artifacts
- Standalone file (no build step) embeds the full data.json inline; real data is used exactly as provided

## Best For

An author who writes often (economics PhD student) and needs a disciplined, beautiful space to review scored items, compose short-form content (letters, posts, replies), and maintain the "nothing leaves without you" boundary. Best on 1440×900 or wider (1100 px minimum).