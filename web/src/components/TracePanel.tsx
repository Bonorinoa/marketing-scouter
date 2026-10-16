import { useState } from "react";
import { BASE } from "../api/client";
import { FACTOR_LABEL, topicLabel } from "../copy";

/** Sprint Wed 4:46: every card is auditable — the source → fit grade → score → draft, from GET /cards/{id}/trace.
 *  Collapsed by default, loads on first open, read-only. */
export interface CardTrace {
  card_id: string; state: string;
  source: { url: string; status_id: string | null; author: string | null; text: string; card_created_at: string | null; age: string | null };
  grade: { asset_id: string; asset_title: string | null; slugs: string[]; claim: string | null; fit_level: string | null;
    filter_source: "word" | "model"; shadow_level: string | null; labels: string[];
    cached_grades: { asset_id: string; level: string; model: string }[];
    shadow_disagreements: { scout_run_id: string; disagreement: string; graded_best_level: string }[] };
  score: { S: number; factors: Record<string, number> | null; note: string };
  draft: { model: string | null; status: string | null; code: string | null; gate: { ok?: boolean; reasons?: { code: string; message: string }[] } | null;
    shown: string; no_draft_line: string | null; copy_enabled: boolean | null; handoff_blocked: string | null };
  events: { ts: string; kind: string; decision?: string; S?: number; kill_reasons?: string[]; scout_run_id?: string }[];
}

const DRAFTER: Record<string, string> = { local_template: "Built-in drafter", xbrief: "x-brief", unknown: "Unknown drafter" };
const when = (ts: string | null | undefined) => {
  if (!ts) return "";
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
};

export function TraceView({ t }: { t: CardTrace }) {
  const reasons = t.draft.gate?.reasons ?? [];
  const shadowOther = t.grade.cached_grades.filter((g) => g.asset_id !== t.grade.asset_id && g.level !== "none").length;
  return (
    <ol className="trace-steps" data-testid="trace-steps">
      <li data-testid="trace-step-source">
        <span className="trace-k">Found</span>
        <span>{t.source.author ?? "Unknown author"} on X{t.source.status_id ? <> · <code className="slug-mono">{t.source.status_id}</code></> : null}
          {t.source.card_created_at ? <> · card made {when(t.source.card_created_at)}</> : null}</span>
      </li>
      <li data-testid="trace-step-grade">
        <span className="trace-k">Fit</span>
        <span>
          {t.grade.asset_title ?? t.grade.asset_id} · {t.grade.slugs.map(topicLabel).join(", ")} ·{" "}
          {t.grade.filter_source === "model" ? "model grade" : "word match"}
          {t.grade.shadow_level ? <> · shadow grade: <strong data-testid="trace-shadow">{t.grade.shadow_level}</strong></> : null}
          {shadowOther > 0 ? <span className="muted"> (also fits {shadowOther} other piece{shadowOther === 1 ? "" : "s"})</span> : null}
        </span>
      </li>
      <li data-testid="trace-step-score">
        <span className="trace-k">Score</span>
        <span>
          <strong>{Math.round(t.score.S)}</strong>
          {t.score.factors ? <> = {Object.entries(t.score.factors).map(([k, v]) => `${FACTOR_LABEL[k as keyof typeof FACTOR_LABEL] ?? k} ${v.toFixed(2)}`).join(" · ")}</> : null}
          <span className="muted"> · likes never count</span>
        </span>
      </li>
      <li data-testid="trace-step-draft">
        <span className="trace-k">Draft</span>
        <span>
          {DRAFTER[t.draft.model ?? "unknown"] ?? t.draft.model} ·{" "}
          {t.draft.shown ? "shown, ready to copy" : t.draft.no_draft_line ? "not shown" : t.draft.handoff_blocked === "no_lens" ? "none (reply in your own words)" : "none yet"}
          {reasons.length > 0 && <> · check: {reasons.map((r) => r.code).join(", ")}</>}
        </span>
      </li>
      <li data-testid="trace-step-events">
        <span className="trace-k">Log</span>
        <span className="trace-events">{t.events.length === 0 ? "No events recorded." : t.events.map((e, i) => (
          <span key={i} className="trace-ev">{when(e.ts)} {e.kind}{e.decision ? `: ${e.decision}` : ""}{e.kill_reasons ? `: ${e.kill_reasons.join(", ")}` : ""}</span>
        ))}</span>
      </li>
    </ol>
  );
}

export function TracePanel({ cardId }: { cardId: string }) {
  const [state, setState] = useState<{ kind: "idle" | "loading" | "error" } | { kind: "ok"; t: CardTrace }>({ kind: "idle" });
  const load = async () => {
    if (state.kind === "ok" || state.kind === "loading") return;
    setState({ kind: "loading" });
    try {
      const r = await globalThis.fetch(`${BASE}/cards/${encodeURIComponent(cardId)}/trace`);
      if (!r.ok) throw new Error(String(r.status));
      setState({ kind: "ok", t: (await r.json()) as CardTrace });
    } catch {
      setState({ kind: "error" });
    }
  };
  return (
    <details className="trace-panel disclosure" data-testid="trace-panel" onToggle={(e) => { if ((e.currentTarget as HTMLDetailsElement).open) void load(); }}>
      <summary>How this card was made</summary>
      {state.kind === "loading" && <p className="muted small" data-testid="trace-loading">Loading the trace…</p>}
      {state.kind === "error" && (
        <p className="muted small" data-testid="trace-error">Couldn't load the trace. <button type="button" className="text-btn" onClick={() => { setState({ kind: "idle" }); void load(); }}>Try again</button></p>
      )}
      {state.kind === "ok" && <TraceView t={state.t} />}
    </details>
  );
}
