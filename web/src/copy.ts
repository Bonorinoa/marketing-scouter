// Plain-language UI copy (UX-FOUNDATIONS-BRIEF §2, §5 + REDESIGN-SESSION-2026-10-10).
// Pipeline words (x-brief, handoff, seal, checksum, lens, receipt) stay off the main chrome.
export const KILL_TEXT: Record<string, string> = {
  empty_fit: "Not about any of your work",
  door_mix: "Mixes your research and civic voices. Pick one piece of work first.",
  cap: "You've hit today's 7 for this outlet.",
  evidence_out: "Evidence too weak to recommend.",
  evidence_c: "Evidence too weak to recommend.",
  expired_handoff: "This opening expired after 72h. Check the post again for a fresh one.",
  s_safe_kill: "Score too low to be worth a reply.",
  no_lens: "No draft style for this topic yet. Reply in your own words.",
  unknown_card: "That opening no longer exists. Refresh Today.",
  unknown_asset: "That piece of work isn't in your list any more.",
  link_only: "Couldn't read that post. Paste its text.",
};
export const WIN_LABEL: Record<string, string> = {
  date: "Date", slug: "Topic", outlet: "Where", asset_id: "Asset", source_id: "Source",
  win_type: "Kind of win", card_id: "Card", note: "Note",
};
export const WIN_TYPE_LABEL: Record<string, string> = {
  claim_named_reply: "Reply that named the claim", warm_intro: "Warm intro", evidence_ab: "Evidence upgrade",
};
const TONE_LABEL: Record<string, string> = {
  "academic-finding": "Research finding", "methods-practical": "Practical methods", "public-essay": "Public essay",
  "builder-readme": "Builder notes", "civic-provincial": "Civic voice", "program-overview": "Program overview",
  "working-notes": "Working notes",
};
export const toneLabel = (t: string | null | undefined) => (t ? TONE_LABEL[t] ?? t : "Voice not set");

/** Door → plain badge (colors kept via door-* classes). */
export const doorLabel = (d: string) =>
  d === "EconLLM" ? "Research voice" : d === "Augusto-civic" ? "Civic voice" : d;

export const TAB_COPY = {
  today: {
    purpose: "Openings where your work fits a live conversation, with a draft ready to edit.",
    empty: "I'm looking for conversations about your work. First openings usually show up within the hour.",
    emptyQuiet: "No strong openings right now.",
  },
  work: {
    purpose: "The pieces you're promoting: papers, repos, essays, cartas.",
    empty: "No assets yet. Add one with its surface, tone, and door so recommendations can be scoped to it.",
  },
  wins: {
    purpose: "Exposure you confirmed actually happened, by asset and outlet.",
    empty: "No wins logged yet. A win counts only after you confirm it happened.",
  },
};

export const BANNER_TEXT = "Suggests only. You post everything yourself.";
export const LINK_ONLY_MSG = "Couldn't read that post. Paste its text.";
export const NO_LENS_OWN_WORDS = "No draft style for this topic yet. Reply in your own words.";

export const killedLine = (code: string) =>
  code === "link_only"
    ? LINK_ONLY_MSG
    : `Not a fit: ${killText(code).replace(/\.$/, "")}. Nothing was queued.`;
export const killText = (code: string) => KILL_TEXT[code] ?? `Scouter skipped this: ${code}.`;

// Basis of the score weights, shown in the score hover (same wording as the README).
export const WEIGHTS_BASIS = "Hand-set by the team and not yet fitted to outcomes. A review of X's open-sourced ranking signals will inform planned changes to Urgency and Format fit.";

export const FACTOR_LABEL: Record<string, string> = {
  Fit: "Fit", Urgency: "Urgency", FormatPrior: "Format fit", Evidence: "Evidence",
  DoorMatch: "Voice match", EffortPenalty: "Effort cost",
};

export const CRITERION_HINTS = ["none", "original_contribution", "published_about", "scholarly_authorship", "judging"] as const;
export const CRITERION_LABEL: Record<string, string> = {
  none: "None (worth logging, no criterion)", original_contribution: "Original contribution (experts engaging your claim)",
  published_about: "Media coverage about you", scholarly_authorship: "Scholarly authorship (citations)",
  judging: "Judging others' work",
};
const HINT_BY_WIN: Record<string, string> = { claim_named_reply: "original_contribution", warm_intro: "none", evidence_ab: "scholarly_authorship" };
export const defaultHint = (w: string | null) => (w ? HINT_BY_WIN[w] ?? "none" : "none");

/** Mirrors the server's refusal (src/win_evidence.py valid_public_url), with https required in the UI. */
export function evidenceUrlProblem(raw: string): string | null {
  const u = raw.trim();
  if (!u) return "Add the public link to the reply, intro or citation.";
  if (/\s/.test(u)) return "That link has spaces in it. Paste the address only.";
  let url: URL;
  try { url = new URL(u); } catch { return "That isn't a web address. It should start with https://."; }
  if (url.protocol !== "https:") return "Use a public link that starts with https://.";
  const h = url.hostname.toLowerCase();
  if (!h.includes(".") || h === "localhost" || h.endsWith(".local") || /^(127\.|10\.|192\.168\.|0\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.)/.test(h) || h.startsWith("["))
    return "That link points to a private or local address. Use the public link others can open.";
  return null;
}

export const KIND_LABEL: Record<string, string> = {
  working_paper: "Working paper", conference: "Conference paper", github: "Repo", medium: "Essay",
  arxiv: "arXiv paper", carta: "Carta", lab: "Lab", substack: "Substack piece",
};
export const kindLabel = (k: string | null | undefined) => (k ? KIND_LABEL[k] ?? k : "");

/** Score word for the card header. */
export function scoreWord(s: number): string {
  if (s >= 85) return "Strong";
  if (s >= 70) return "Good";
  if (s >= 55) return "Fair";
  return "Weak";
}

/** Topic slug → human label (Designer P2 #6). Plain-words; Marketing to review. */
export const TOPIC_LABEL: Record<string, string> = {
  "sca-nonweird": "synthetic agents beyond WEIRD samples",
  "sca-pilot-ethics": "ethics of synthetic-population pilots",
  "sca-rag-profiles": "RAG cultural profiles vs naive persona prompts",
  "cvp-measurement-layer": "construct-validity measurement layer",
  "cvp-not-identification": "fragility audit, not causal identification",
  "cvp-empty-finding": "empty admissible set as a finding",
  "smart-surveys": "LLM-assisted survey generation",
  "campus-odqa": "campus open-domain QA",
  "gpt4o-weird": "GPT-4o-mini leaning toward WEIRD values",
  "cheap-gen-scarce-verify": "cheap generation, scarce local verification",
  "abm-nroy-policy": "plausible policy worlds (NROY ranges)",
  "econllm-lab": "games, experiments, LLM agents and complex systems",
  "ai-society-governance": "AI governance of incentives and norms",
  "verification-local-context": "verified local context as a public good",
  "civic-policy-simulation": "simulations as civic decision aids",
  "complexity-policy": "feedback and emergence in policy design",
  "abm-organizations": "ABMs linking micro rules to org outcomes",
  "econ-ai-cas": "econ experiments, LLM agents, and CAS methods",
  "synthetic-societies-validity": "validating artificial societies across cultures",
  "human-ai-collective-action": "human–AI systems as the unit of analysis",
  "ai-measurement-policy": "construct-validity audits before AI policy",
};

/** Asset id → short fit-line name (Designer: "SCA paper", not the full title). */
export const ASSET_SHORT: Record<string, string> = {
  asset_sca_nonweird: "SCA paper",
  asset_cvprofiles: "cvprofiles package",
  asset_gpt4o_weird: "GPT4o is WEIRD essay",
  asset_adepa_lagaceta_carta: "Adepa carta",
  asset_econllm_lab: "EconLLM Lab",
  asset_smart_surveys: "Smart Surveys paper",
  asset_complexity_policy: "complexity-policy notes",
  asset_abm_organizations: "ABM organizations notes",
};

/** Why-it-fits one-liner: short asset name + human topic label (never hyphen-swapped slug). */
export function whyFits(card: {
  slug: string;
  asset: { title: string; asset_id?: string };
  claim?: string;
}): string {
  const short =
    (card.asset.asset_id && ASSET_SHORT[card.asset.asset_id]) || card.asset.title;
  const topic = TOPIC_LABEL[card.slug] || card.slug.replace(/-/g, " ");
  return `Matches your ${short}: ${topic}.`;
}

export function topicLabel(slug: string): string {
  return TOPIC_LABEL[slug] || slug.replace(/-/g, " ");
}

// Language cap (X only), docs/TAB-COPY.md "Language cap"
export const LANG_CHIP = "Not clearly English";
export const LANG_TOOLTIP =
  "Your X account is English-only. This text isn't clearly English, so it gets no claim draft. Ranked as a topic card.";
export function langTraceLine(trace?: { lang?: string | null; reason?: string | null } | null): string | null {
  if (!trace) return null;
  const reason = trace.reason === "non_latin_script" ? "non_latin_script" : "lang_capped";
  return `Language: ${trace.lang || "unknown"} · capped at topic (${reason})`;
}

/** Drafter declined (Researcher copy 2026-10-14). The reason is untrusted model text: always sanitizeReason it. */
export const NO_DRAFT_TOOLTIP = "The drafter read this and chose not to reply. You can still reply yourself from the handoff.";
export const NO_DRAFT_MAX = 140;
export function sanitizeReason(raw: string | null | undefined): string {
  if (!raw) return "";
  let s = String(raw).normalize("NFKC");
  s = s.replace(/[\p{C}\p{Z}]/gu, (c) => (c === " " ? c : " "));
  s = s.replace(/<[^>]*>/g, " ").replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1");
  s = s.replace(/\b(?:https?:\/\/|www\.)\S*/gi, " ");
  s = s.replace(/\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\/\S*)?/gi, " ");
  s = s.replace(/(^|[^\w])@\w+/g, "$1 ");
  s = s.replace(/[*_`#>|~[\]]+/g, " ");
  s = s.replace(/\s+/g, " ").trim().replace(/\s+([,.;:!?])/g, "$1");
  if (s.length > NO_DRAFT_MAX) {
    let cut = s.slice(0, NO_DRAFT_MAX - 1);
    if (cut.includes(" ")) cut = cut.slice(0, cut.lastIndexOf(" "));
    s = cut.replace(/[ ,;:.-]+$/, "") + "…";
  }
  return s;
}
export const noDraftLine = (reason: string | null | undefined) =>
  `No draft: the drafter passed on this one. Reason: ${sanitizeReason(reason) || "none given."}`;

/** View-time draft cleanup (mirror of src/api/draft_view.py; copy by Researcher, docs/TAB-COPY.md). */
export const TEMPLATE_NO_DRAFT_LINE = "No draft: the basic drafter can only repeat your claim, so this one is left blank.";
export const COPY_WITH_CAVEAT_LABEL = "Copy with caveat";
export const COPY_WITH_CAVEAT_TOOLTIP = "Copies the draft with the caveat as its last line. Whether readers see the caveat is your call.";
const flat = (s: string) => s.normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();
const escRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** Remove a verbatim caveat (case/space/trailing-punctuation insensitive). */
export function stripCaveat(text: string | null | undefined, caveat: string | null | undefined): string {
  const t = (text ?? "").normalize("NFKC");
  const c = (caveat ?? "").normalize("NFKC").trim().replace(/[.!?…]+$/, "");
  if (!t || !c) return t.trim();
  const re = new RegExp("\\s*" + c.split(/\s+/).map(escRe).join("\\s+") + "[.!?…]?", "gi");
  return t.replace(re, " ").replace(/[ \t]{2,}/g, " ").trim();
}
export const caveatIn = (text: string, caveat: string | null | undefined) => {
  const c = flat(caveat ?? "").replace(/[.!?…]+$/, "");
  return !!c && flat(text).includes(c);
};
