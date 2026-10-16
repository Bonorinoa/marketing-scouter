"""Dark academic design tokens + custom CSS for Streamlit."""

from __future__ import annotations

# Distinctive, calm — indigo / amber, no AI-slop gradient blob
TOKENS = {
    "bg": "#0e1117",
    "surface": "#161b22",
    "surface2": "#1c2330",
    "border": "#2a3344",
    "text": "#e8eaed",
    "muted": "#9aa3b2",
    "indigo": "#6c8cff",
    "indigo_dim": "#3d4f8a",
    "amber": "#e6b35a",
    "amber_dim": "#8a6a2e",
    "success": "#5dbe8a",
    "danger": "#e06c75",
    "chip_bg": "#243049",
}


def inject_css() -> str:
    t = TOKENS
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {{
  font-family: 'IBM Plex Sans', system-ui, sans-serif;
}}

.stApp {{
  background: {t['bg']};
  color: {t['text']};
}}

h1, h2, h3 {{
  font-family: 'IBM Plex Serif', Georgia, serif !important;
  letter-spacing: -0.02em;
  color: {t['text']} !important;
}}

/* Header band */
.ms-hero {{
  background: linear-gradient(135deg, {t['surface']} 0%, {t['surface2']} 60%, #1a2235 100%);
  border: 1px solid {t['border']};
  border-radius: 14px;
  padding: 1.25rem 1.5rem;
  margin-bottom: 1rem;
}}
.ms-hero h1 {{
  margin: 0 0 0.25rem 0;
  font-size: 1.75rem;
}}
.ms-hero .ms-sub {{
  color: {t['muted']};
  font-size: 0.95rem;
  margin: 0;
}}
.ms-badge {{
  display: inline-block;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: {t['amber']};
  border: 1px solid {t['amber_dim']};
  background: rgba(230, 179, 90, 0.08);
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  margin-bottom: 0.5rem;
}}

/* Queue card */
.ms-card {{
  background: {t['surface']};
  border: 1px solid {t['border']};
  border-left: 3px solid {t['indigo']};
  border-radius: 12px;
  padding: 1rem 1.15rem;
  margin-bottom: 0.85rem;
}}
.ms-card.civic {{
  border-left-color: {t['amber']};
}}
.ms-card-head {{
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.75rem;
  margin-bottom: 0.5rem;
}}
.ms-score {{
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.35rem;
  font-weight: 500;
  color: {t['indigo']};
}}
.ms-meta {{
  color: {t['muted']};
  font-size: 0.82rem;
}}
.ms-draft {{
  background: {t['surface2']};
  border: 1px solid {t['border']};
  border-radius: 8px;
  padding: 0.75rem 0.9rem;
  font-size: 0.92rem;
  line-height: 1.45;
  white-space: pre-wrap;
  margin: 0.6rem 0;
}}
.ms-chip {{
  display: inline-block;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  background: {t['chip_bg']};
  color: {t['text']};
  border-radius: 6px;
  padding: 0.18rem 0.45rem;
  margin: 0.15rem 0.25rem 0.15rem 0;
}}
.ms-chip.fit {{ border-bottom: 2px solid {t['indigo']}; }}
.ms-chip.urgency {{ border-bottom: 2px solid {t['amber']}; }}
.ms-chip.evidence {{ border-bottom: 2px solid {t['success']}; }}
.ms-chip.warn {{ color: {t['danger']}; }}

.ms-empty {{
  text-align: center;
  padding: 2.5rem 1rem;
  color: {t['muted']};
  border: 1px dashed {t['border']};
  border-radius: 12px;
  background: {t['surface']};
}}

.ms-gate {{
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem;
  color: {t['muted']};
  border-top: 1px solid {t['border']};
  margin-top: 1.5rem;
  padding-top: 0.75rem;
}}

/* Streamlit chrome polish */
div[data-testid="stMetricValue"] {{
  font-family: 'IBM Plex Mono', monospace;
}}
.stTabs [data-baseweb="tab"] {{
  font-family: 'IBM Plex Sans', sans-serif;
}}
section[data-testid="stSidebar"] {{
  background: {t['surface']};
  border-right: 1px solid {t['border']};
}}
</style>
"""


def hero_html() -> str:
    return """
<div class="ms-hero">
  <div class="ms-badge">Suggests only · never posts</div>
  <h1>Market Scouter</h1>
  <p class="ms-sub">Augusto Bonorino · PhD/CSS + O-1A exposure · paste → score → door-shaped draft</p>
</div>
"""


def factor_chips_html(factors: dict, S: float) -> str:
    order = [
        ("Fit", "fit"),
        ("Urgency", "urgency"),
        ("FormatPrior", ""),
        ("Evidence", "evidence"),
        ("DoorMatch", ""),
        ("EffortPenalty", "warn" if factors.get("EffortPenalty", 0) else ""),
    ]
    chips = [f'<span class="ms-score">{S:.1f}</span>']
    for key, cls in order:
        val = factors.get(key, 0)
        chips.append(f'<span class="ms-chip {cls}">{key} {val:g}</span>')
    return " ".join(chips)


def card_html(
    *,
    title: str,
    url: str,
    door: str,
    move: str,
    slugs: list[str],
    draft: str,
    S: float,
    factors: dict,
    asset_title: str,
    author: str | None = None,
    playbook: list[str] | None = None,
    t_status: str = "unknown",
) -> str:
    civic = "civic" if "civic" in (door or "").lower() else ""
    slug_chips = " ".join(f'<span class="ms-chip">{s}</span>' for s in slugs)
    pb = " · ".join(playbook or [])
    author_s = f" · {author}" if author else ""
    return f"""
<div class="ms-card {civic}">
  <div class="ms-card-head">
    <div>
      <strong>{title[:120]}{"…" if len(title) > 120 else ""}</strong>
      <div class="ms-meta">{door} · {move} · T={t_status}{author_s}</div>
      <div class="ms-meta">Matched: {asset_title}</div>
    </div>
    <div>{factor_chips_html(factors, S)}</div>
  </div>
  <div>{slug_chips}</div>
  <div class="ms-draft">{draft}</div>
  <div class="ms-meta"><a href="{url}" target="_blank" rel="noopener">Open deep link ↗</a>
    {" · " + pb if pb else ""}</div>
</div>
"""
