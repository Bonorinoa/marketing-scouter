# x-brief Interests seed — closed set from Market Scouter `fit-tags.md`

**Rule:** compose, do not merge. Seed `Profile/Interests.md` Active list from this file only.
Jev may rank *within* Active; it must not invent a free-form lens outside these slugs.
Handoff from Scouter → `x-brief add <url>` carries matched slug(s) + door + claim + Evidence grade.
If Jev’s confirmed lens ≠ Scout matched slug → log ScoutEvent `lens_mismatch`; do not rewrite Fit.

## x-brief Active (synced with `~/Documents/x-brief-vault/Profile/Interests.md`)
All 21 stay in the closed Fit vocabulary. Only `xbrief_active: true` slugs are handed off, in `xbrief_rank` order. A card whose topics are all inactive gets `no_lens` ("x-brief has no lens for this topic yet").

## Door filter (per handoff)
- One door per card. Pause the other door’s interests (or pass only door-matching Active) before Review.
- Dual-door slugs (`ai-society-governance`, `human-ai-collective-action`): door comes from the Scout card, not from inventing a new claim.

## Paste into x-brief `Profile/Interests.md` (marked region)

## Active
- `sca-nonweird` [EconLLM] — LLM-as-subjects, WEIRD bias, cultural alignment, synthetic participants (use when: ) · xbrief_active: true; xbrief_rank: 1
- `sca-pilot-ethics` [EconLLM] — SCAs are a cheap/ethical way to pilot hard-to-reach population experiments before field work (use when: expensive RCTs, hard-to-reach samples, pilot design) · xbrief_active: false; xbrief_rank: -
- `sca-rag-profiles` [EconLLM] — persona prompting, RAG for agents, prompt engineering for culture (use when: ### 2. cvprofiles (PyPI / methods package + LinkedIn methods posts)) · xbrief_active: true; xbrief_rank: 2
- `cvp-measurement-layer` [EconLLM] — LLM construct scores, Big Five-on-LLMs, “which prompt is valid” (use when: ) · xbrief_active: true; xbrief_rank: 3
- `cvp-empty-finding` [EconLLM] — failed personality batteries, collapsing traits, null robustness (use when: ### 3. Smart Surveys (CSEDU 2023)) · xbrief_active: false; xbrief_rank: -
- `cvp-not-identification` [EconLLM] — Result lives in θ / network choice — fragility audit, not causal ID (use when: people treating measurement audits as identification) · xbrief_active: true; xbrief_rank: 4
- `gpt4o-weird` [EconLLM] — cultural bias of GPT, WVS, alignment to Global South (use when: ### 6. Op-eds / Adepa / La Gaceta (when published)) · xbrief_active: false; xbrief_rank: -
- `synthetic-societies-validity` [EconLLM] — Artificial societies are useful only when behavior is validated across cultures, tasks and models (use when: generative agents, social simulation, external validity, SCA) · xbrief_active: false; xbrief_rank: -
- `econ-ai-cas` [EconLLM] — Economic experiments + LLM agents + CAS methods form one program for studying heterogeneous behavior and policy (use when: computational social science, artificial societies, agentic economies) · xbrief_active: false; xbrief_rank: -
- `econllm-lab` [EconLLM] — EconLLM Lab uses games/experiments to both pilot econ research and evaluate LLM preferences (use when: EconLLM recruiting, lab methods, evaluating LLMs with games) · xbrief_active: false; xbrief_rank: -
- `ai-measurement-policy` [EconLLM] — Policy cannot outrun measurement: cheap AI proxies need construct-validity audits before downstream decisions (use when: algorithmic audits, scoring systems, AI evaluation, public-sector deployment) · xbrief_active: true; xbrief_rank: 5
- `verification-local-context` [Augusto-civic] — Cheap generation/amplification makes verified local context a scarce public good (use when: misinformation, journalism, Community Notes, regional/national narrative gaps) · xbrief_active: false; xbrief_rank: -
- `cheap-gen-scarce-verify` [Augusto-civic] — misinfo, Community Notes, AI and journalism, Adepa (use when: ### 7. Working / in-progress (use lightly until public)) · xbrief_active: false; xbrief_rank: -
- `ai-society-governance` [Augusto-civic] — `Augusto-civic` or `EconLLM` (use when: AI governance should shape incentives, norms and information architecture—not collapse into ban-vs-hype) · xbrief_active: true; xbrief_rank: 9
- `human-ai-collective-action` [Augusto-civic] — `Augusto-civic` or `EconLLM` (use when: The unit of analysis is often the human–AI information system, not the model alone) · xbrief_active: true; xbrief_rank: 10
- `complexity-policy` [EconLLM] — Complex policy problems require feedback, emergence and adaptation—not only equilibrium or one-shot optimization (use when: complexity economics, adaptive governance, policy design) · xbrief_active: true; xbrief_rank: 6
- `civic-policy-simulation` [EconLLM] — Simulations are decision aids for civic policy when assumptions, calibration and uncertainty stay visible (use when: digital twins, policy sandboxes, participatory modeling, municipal AI) · xbrief_active: false; xbrief_rank: -
- `abm-organizations` [EconLLM] — Agent-based models connect micro rules and organizational structure to emergent outcomes (use when: firms, networks, institutional change, org design, NetLogo) · xbrief_active: true; xbrief_rank: 7
- `abm-nroy-policy` [EconLLM] — ABM policy, history matching, causal ID under interference (use when: ) · xbrief_active: true; xbrief_rank: 8
- `smart-surveys` [EconLLM] — survey design automation, AI for questionnaires (use when: ### 4. Open-domain QA in college setting (CSEDU w/ Lauría & Presutti, 2022)) · xbrief_active: false; xbrief_rank: -
- `campus-odqa` [EconLLM] — campus AI copilots, institutional QA, edtech RAG (use when: ### 5. Medium / public essays (e.g. “GPT4o is WEIRD!”)) · xbrief_active: false; xbrief_rank: -

## Paused

- *(none — pause Perwell/Loop Pilot forever; they are anti-tags, never interests)*

## Anti-tags (never seed)
- Loop Pilot / monotributo / Perwell pricing
- “AI agent product” pitches
- Invented ER / Buffer absolute %

## Suggested Scouter → x-brief export payload (JSON)
```json
{
  "url": "https://x.com/.../status/...",
  "matched_slugs": ["sca-nonweird"],
  "door": "EconLLM",
  "claim_one_liner": "...",
  "evidence_grade": "A",
  "oped_status": null,
  "scout_card_id": "card_...",
  "interest_seed_closed": true
}
```

_Generated from fit-tags.md — 21 closed interests._
