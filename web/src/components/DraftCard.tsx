import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";

/** In-app x-brief draft (BUILD-LOG 2026-10-09 17:45). Never posts, never writes a receipt or Win.
 *  authored_by is SERVER-set: the UI only displays it and never sends or computes it. */
export interface Reason { code: string; message: string }
export interface DraftState {
  draft_text: string; authored_by: string; gate: { ok: boolean; reasons: Reason[] } | null;
  copy_enabled: boolean; warnings: Reason[]; outlet?: string | null;
}
type Phase = "idle" | "pending" | "ready" | "error";

/** X counting: every URL counts as 23 characters. */
export function xLength(t: string): number {
  return t.replace(/https?:\/\/\S+/g, "x".repeat(23)).length;
}
export const authorLabel = (a: string | undefined) => (a === "model" ? "Model draft" : "Your edit");

const plain = (e: unknown, fallback: string) =>
  (e as { message?: string } | undefined)?.message ?? fallback;

export function DraftCard({ handoffId, outlet, what, onFallback, onCopied, debounceMs = 400 }: {
  handoffId: string; outlet: string; what: string; onFallback: () => void;
  onCopied?: (text: string) => void; debounceMs?: number;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [err, setErr] = useState("");
  const [text, setText] = useState("");
  const [d, setD] = useState<DraftState | null>(null);
  const [checking, setChecking] = useState(false);
  const [copied, setCopied] = useState(false);
  const inflight = useRef(false); // double-click guard, independent of render timing
  const seq = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(timer.current), []);
  // On reload / reopen: restore the saved draft (GET never runs x-brief).
  useEffect(() => {
    let alive = true;
    api.GET("/handoff/{handoff_id}/draft", { params: { path: { handoff_id: handoffId } } }).then((r) => {
      const b = r.data as unknown as DraftState | null | undefined;
      if (alive && b?.draft_text && !inflight.current) { setD({ ...b, warnings: b.warnings ?? [] }); setText(b.draft_text); setPhase("ready"); }
    }).catch(() => {});
    return () => { alive = false; };
  }, [handoffId]);

  const start = async () => {
    if (inflight.current) return;
    inflight.current = true; setPhase("pending"); setErr("");
    try {
      const r = await api.POST("/handoff/{handoff_id}/draft", { params: { path: { handoff_id: handoffId } } });
      const body = r.data as unknown as DraftState & { status?: string } | undefined;
      const code = (r.error as { code?: string } | undefined)?.code;
      if (r.response.status === 409) { setErr("Already drafting this card."); setPhase("idle"); return; }
      if (code === "door_required") { setErr("This card has no voice set, so drafting can't run. Set the asset's voice, then try again."); setPhase("error"); onFallback(); return; }
      if (!r.response.ok || !body || body.status !== "ok" || !body.draft_text) {
        setErr(plain(r.error, "Drafting didn't return a draft. Copy the details instead."));
        setPhase("error"); onFallback(); return;
      }
      setD({ ...body, warnings: body.warnings ?? [] }); setText(body.draft_text); setPhase("ready");
    } catch {
      setErr("Drafting isn't reachable right now. Copy the details instead."); setPhase("error"); onFallback();
    } finally { inflight.current = false; }
  };

  const recheck = (t: string) => {
    clearTimeout(timer.current);
    const my = ++seq.current;
    setChecking(true);
    timer.current = setTimeout(async () => {
      try {
        const r = await api.POST("/handoff/{handoff_id}/draft/check", {
          params: { path: { handoff_id: handoffId } }, body: { draft_text: t } });
        if (my !== seq.current) return; // a newer edit superseded this check
        if (r.data) setD((prev) => ({ ...(prev as DraftState), ...(r.data as unknown as DraftState), draft_text: t }));
        else setD((prev) => prev && { ...prev, copy_enabled: false, gate: { ok: false, reasons: [{ code: "check_failed", message: plain(r.error, "Couldn't check this edit. Try again.") }] } });
      } catch {
        if (my === seq.current) setD((prev) => prev && { ...prev, copy_enabled: false });
      } finally { if (my === seq.current) setChecking(false); }
    }, debounceMs);
  };

  const copyFinal = async () => {
    if (!d?.copy_enabled || checking) return;
    try { await navigator.clipboard.writeText(text); } catch { setErr("Couldn't copy. Select the draft text and copy it yourself."); return; }
    setErr(""); setCopied(true); onCopied?.(text); // never a receipt, never a Win
    setTimeout(() => setCopied(false), 2000);
  };

  const n = xLength(text);
  const blocked = d?.gate && !d.gate.ok ? d.gate.reasons : [];
  return (
    <section className="xdraft" data-testid="xdraft" data-phase={phase}>
      {(phase === "idle" || phase === "pending") && (
        <button className="primary" data-testid="draft-start" onClick={start} disabled={phase === "pending"} aria-busy={phase === "pending"}>
          {phase === "pending" && <span className="spinner" aria-hidden="true" />}
          {phase === "pending" ? "Writing a draft…" : "Write a draft"}
        </button>
      )}
      {(phase === "idle" || phase === "pending") && <p className="muted small" data-testid="draft-note">Drafting can take a minute.</p>}
      {phase === "idle" && err && <p className="plain-msg" data-testid="draft-busy">{err}</p>}
      <p className="sr-only" aria-live="polite" data-testid="draft-live">
        {phase === "pending" ? "Writing a draft…" : phase === "ready" ? "Draft ready" : phase === "error" ? err : ""}
      </p>
      {phase === "error" && <p className="plain-msg" data-testid="draft-error">{err}</p>}
      {phase === "ready" && d && (
        <>
          <div className="xdraft-head">
            <label htmlFor="xdraft-text" className={`author-tag author-${d.authored_by === "model" ? "model" : "user"}`} data-testid="draft-author">
              {authorLabel(d.authored_by)}
            </label>
            {outlet === "x" && <span className={`count${n > 280 ? " over" : ""}`} data-testid="draft-count">{n} / 280</span>}
          </div>
          <textarea id="xdraft-text" data-testid="draft-text" rows={6} value={text}
            onChange={(e) => { setText(e.target.value); recheck(e.target.value); }} />
          {blocked.length > 0 && (
            <div className="guidance" data-testid="gate-reasons" role="note">
              <p className="guidance-title">Before you copy it</p>
              <ul>{blocked.map((r, i) => <li key={i} data-code={r.code}>{r.message}</li>)}</ul>
            </div>
          )}
          {d.warnings.length > 0 && (
            <ul className="notes" data-testid="draft-warnings" aria-label="Notes on this draft">
              {d.warnings.map((w, i) => <li key={i} data-code={w.code}>{w.message}</li>)}
            </ul>
          )}
          <div className="row">
            <button className="primary" data-testid="copy-final" onClick={copyFinal} disabled={!d.copy_enabled || checking}>
              {copied ? "Copied ✓" : checking ? "Checking…" : "Copy final"}
            </button>
            {copied && <span className="muted" data-testid="copy-final-done">Copied for {what}</span>}
            {err && <span className="plain-msg">{err}</span>}
          </div>
          <p className="muted small">You share it yourself. Copying doesn't record anything.</p>
        </>
      )}
    </section>
  );
}
