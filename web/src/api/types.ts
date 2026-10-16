// View models mirroring src/api/core.py dict shapes (asset_view / card_view / handoff payload).
// The Python truth layer computes every value; the SPA only renders.
export type Door = "EconLLM" | "Augusto-civic";
export interface Asset {
  asset_id: string; title: string; url: string | null; type: string; surface: string | null;
  tone_hint: string | null; caveat?: string | null; door: Door; slugs: string[]; primary_slug: string | null;
  evidence_grade: string; evidence_status: "hard" | "soft_pending" | "out"; oped_status: string | null;
  lang: "es" | "en"; tone: string; format?: "op-ed" | "social";
}
export const S9_FACTORS = ["Fit", "Urgency", "FormatPrior", "Evidence", "DoorMatch", "EffortPenalty"] as const;
export type Factors = Record<(typeof S9_FACTORS)[number], number>;
export interface Card {
  card_id: string; url: string; outlet: "x" | "linkedin"; door: Door; slug: string; slugs: string[];
  claim: string; S: number; factors: Factors; likes_info: number | null; T_status: string; state: string;
  fit_trace?: { lang?: { lang?: string | null; reason?: string | null } | null; [k: string]: unknown } | null;
  move: string; draft: string | null; lang: "es" | "en"; mode: "scoped" | "general"; asset: Asset;
  source_chip: string | null; format?: "op-ed" | "social"; xbrief_slugs?: string[]; handoff_blocked?: string | null;
  labels?: string[];
  fit_level?: string | null;
  rank_reason?: { tier: "claim" | "topic"; text: string; tooltip: string } | null;
  /** Source thread fields (author handle, body, age) — required for Openings. */
  author?: string | null;
  post_text?: string | null;
  age?: string | null;
  age_hours?: number | null;
  created_at?: string | null;
  later_until?: string | null;
  caveat?: string | null;
  no_draft?: boolean; no_draft_line?: string | null; copy_enabled?: boolean | null;
  draft_with_caveat?: string | null; copy_with_caveat_label?: string | null; copy_with_caveat_tooltip?: string | null;
  predraft?: { status?: string | null; code?: string | null; message?: string | null; decline_reason?: string | null; tooltip?: string | null; [k: string]: unknown } | null;
}
export interface RecommendResult {
  ok: boolean; mode: "scoped" | "general"; status: string; kill_id?: string; kill_reasons: string[];
  slugs: string[]; card: Card | null; asset_options?: Asset[]; replaced_card_id?: string | null;
}
export interface HandoffPayload {
  handoff_id: string; scout_card_id: string; url: string; matched_slugs: string[]; scout_slug: string;
  door: Door; claim_one_liner: string; evidence_grade: string; evidence_status: string;
  oped_status: string | null; asset_id: string; asset_type: string; outlet: string;
  interest_seed_closed: true; xbrief_interests: { active: string[]; paused: string[] };
  pause_checksum: string; lang: "es" | "en"; expires_at: string;
  xbrief_slugs?: string[]; xbrief_active_count?: number;
}
export interface Handoff { payload: HandoffPayload; seal: string }
export interface PendingHandoff extends Handoff { status: string; expires_at: string; asset_title: string }
export interface ReplyBudget { used: number; max: number; left: number }
/** cap = queue slots held (n/7); replies_today = daily reply budget the status line and buttons read. */
export interface QueueView { selected_asset: Asset | null; cap: Record<string, string>; cards: Card[]; later?: Card[];
  replies_today?: Record<string, ReplyBudget> }
export interface WinRow {
  date: string; slug: string; outlet: string; asset_id: string | null; source_id: string | null;
  win_type: string; card_id: string; note: string;
}
// Mirrors src/win_export.py WIN_SHEET_COLUMNS (asset_id included).
export const WIN_COLUMNS = ["date", "slug", "outlet", "asset_id", "source_id", "win_type", "card_id", "note"] as const;
export const WIN_TYPES = ["claim_named_reply", "warm_intro", "evidence_ab"] as const;

export interface StatusView {
  x_last_checked: { at: string | null; sentence: string; run_id: string | null };
  drafting_ok: boolean;
  drafting_reason: string;
  drafting_checked_at?: string | null;
  xbrief_selfcheck: { ok: boolean; note?: string };
  queue_size: number;
  queue_by_outlet: Record<string, number>;
  queue_sentence: string;
}
