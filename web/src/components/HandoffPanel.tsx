import { useEffect, useRef, useState } from "react";
import { WIN_TYPES, type Handoff } from "../api/types";
import { CLOSED_INTERESTS, CLOSED_SLUGS } from "../interestsSeed";
import { DraftCard } from "./DraftCard";
import { CRITERION_HINTS, CRITERION_LABEL, WIN_TYPE_LABEL, defaultHint, doorLabel, evidenceUrlProblem } from "../copy";

export interface ReceiptDraft {
  action: "acted" | "edited" | "skipped"; confirmed_lens: string | null; win_type: string | null; attested: boolean;
  evidence_url?: string | null; criterion_hint?: string | null;
}

function expiresIn(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  if (!isFinite(ms)) return iso;
  if (ms <= 0) return "expired";
  const h = Math.round(ms / 3.6e6);
  return h >= 24 ? `in ${Math.round(h / 24)}d` : `in ${h}h`;
}
export { expiresIn };

/** Sealed handoff → x-brief as a drawer (desktop) / bottom sheet (mobile).
 *  Interests list is the closed seed only; no free-form interest input exists.
 *  The payload carries item, asset, door and slugs only — never writing samples or draft text. */
export function HandoffPanel({ handoff, onReceipt, onClose, onCopy, assetTitle, startAtReceipt, receiptError }: {
  handoff: Handoff; onReceipt?: (r: ReceiptDraft) => Promise<unknown> | void; onClose?: () => void;
  onCopy?: (text: string) => void; assetTitle?: string; startAtReceipt?: boolean; receiptError?: string | null;
}) {
  const p = handoff.payload;
  const civic = p.door === "Augusto-civic";
  const active = new Set(p.xbrief_interests.active);
  const outsideSeed = p.xbrief_interests.active.filter((s) => !CLOSED_SLUGS.has(s));
  const econPaused = CLOSED_INTERESTS.filter((i) => i.door === "EconLLM").every((i) => !active.has(i.slug));
  const [r, setR] = useState<ReceiptDraft>({ action: "acted", confirmed_lens: null, win_type: null, attested: false, evidence_url: "", criterion_hint: "none" });
  const [hintTouched, setHintTouched] = useState(false);
  const [fallback, setFallback] = useState(false); // x-brief error/timeout → show the clipboard handoff
  const receiptRef = useRef<HTMLFormElement>(null);
  useEffect(() => { if (startAtReceipt) receiptRef.current?.scrollIntoView?.({ block: "start" }); }, [startAtReceipt]);
  const [copied, setCopied] = useState(false);
  const headRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    if (!startAtReceipt) headRef.current?.focus();
    return () => { prev?.focus?.(); }; // focus-not-restored: return focus to the button that opened the drawer
  }, []);
  const [copyFailed, setCopyFailed] = useState(false);
  const [answer, setAnswer] = useState<"yes" | "not_yet" | "skip">("yes");
  const text = JSON.stringify(handoff, null, 2);
  const what = `${assetTitle ?? p.asset_id}, ${p.door}`;
  const lens = p.xbrief_slugs ?? p.matched_slugs;
  const [busy, setBusy] = useState(false);
  const [everCopied, setEverCopied] = useState(false);
  const step = r.attested ? 3 : everCopied || startAtReceipt ? 2 : 1;
  const needsEvidence = answer === "yes" && !!r.win_type;
  const evProblem = needsEvidence ? evidenceUrlProblem(r.evidence_url ?? "") : null;
  const [evTouched, setEvTouched] = useState(false);
  const copy = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("no clipboard");
      await navigator.clipboard.writeText(text);
    } catch {
      setCopyFailed(true); setCopied(false); return; // never claim "Copied" when it wasn't
    }
    setCopyFailed(false); setCopied(true); setEverCopied(true); onCopy?.(`Copied for ${what}`);
    setTimeout(() => setCopied(false), 2000);
  };
  const submit = async () => {
    if (answer === "not_yet") { onClose?.(); return; }
    if (!r.attested || busy) return;
    if (evProblem) { setEvTouched(true); return; }
    setBusy(true); const t0 = Date.now();
    const out: ReceiptDraft = needsEvidence ? { ...r, evidence_url: (r.evidence_url ?? "").trim() } : { ...r, evidence_url: null, criterion_hint: r.win_type ? r.criterion_hint : null };
    try { await onReceipt?.(out); } finally { setTimeout(() => setBusy(false), Math.max(0, 300 - (Date.now() - t0))); }
  };
  return (
    <aside className="drawer" data-testid="handoff-panel" data-door={p.door} role="dialog" aria-labelledby="ho-title">
      <header className="drawer-head">
        <h3 id="ho-title" ref={headRef} tabIndex={-1}>Reply ready · <span className={`door door-${p.door}`}>{doorLabel(p.door)}</span></h3>
        {onClose && <button className="text-btn" onClick={onClose} aria-label="Close">Not yet</button>}
      </header>
      <ol className="steps" data-testid="handoff-steps">
        {["Copied", "Did you post it?", "Confirmed"].map((s, i) => (
          <li key={s} className={i + 1 < step ? "done" : i + 1 === step ? "current" : ""} aria-current={i + 1 === step ? "step" : undefined}>{s}</li>
        ))}
      </ol>
      <p className="muted" data-testid="sealed-line">Expires {expiresIn(p.expires_at)} · uses {lens.length} of {p.xbrief_active_count ?? 10} topics</p>
      {civic && (
        <p className="warn" data-testid="econllm-paused" data-paused={String(econPaused)}>
          Research voice paused for this civic reply (one voice at a time)
        </p>
      )}
      {outsideSeed.length > 0 && <p className="error" data-testid="seed-violation">refused: {outsideSeed.join(", ")} outside closed seed</p>}
      {!startAtReceipt && <DraftCard handoffId={p.handoff_id} outlet={p.outlet} what={what}
        onFallback={() => setFallback(true)} onCopied={() => setEverCopied(true)} />}
      {fallback && <p className="muted" data-testid="fallback-note">Copy the details below and draft the reply yourself.</p>}
      <details className="disclosure" data-testid="manual-handoff" open={fallback || startAtReceipt || undefined}>
        <summary>Copy details instead</summary>
      <button className={fallback ? "primary" : "secondary"} data-testid="copy-handoff" onClick={copy}>{copied ? `Copied ✓ for ${what}` : "Copy details"}</button>
      <p className="sr-only" aria-live="polite" data-testid="copy-status">{copied ? `Copied for ${what}` : copyFailed ? "Couldn't copy" : ""}</p>
      {copyFailed && (
        <div className="copy-fallback" data-testid="copy-failed">
          <p className="error">Couldn't copy — select the text below and copy it yourself.</p>
          <textarea readOnly value={text} rows={6} aria-label="Details text" onFocus={(e) => e.currentTarget.select()} />
          <button className="text-btn" onClick={() => { setCopyFailed(false); setEverCopied(true); }}>I copied it</button>
        </div>
      )}
      
        {fallback && <textarea readOnly value={text} rows={6} data-testid="fallback-text" aria-label="Details text (fallback)" onFocus={(e) => e.currentTarget.select()} />}
      </details>
      <details className="disclosure">
        <summary>Which topics this uses ({lens.length} of {p.xbrief_active_count ?? 10}: {lens.join(", ")})</summary>
        <ul className="interests" data-testid="closed-fit-list">
          {CLOSED_INTERESTS.map((i) => {
            const isActive = active.has(i.slug);
            return (
              <li key={i.slug} data-slug={i.slug} data-state={isActive ? "active" : "paused"} className={isActive ? "active" : "paused"}>
                <code>{i.slug}</code> <span className="muted">[{i.door}]</span>
                {isActive ? <span className="muted"> Active</span> : <span className="pill-paused">Paused</span>}
              </li>
            );
          })}
        </ul>
      </details>
      <details data-testid="payload-preview" className="disclosure">
        <summary>Payload preview</summary>
        <p className="muted small sr-only">Checksum <code data-testid="pause-checksum">{p.pause_checksum.slice(0, 12)}…</code></p>
        <pre lang={p.lang}>{JSON.stringify(p, null, 2)}</pre>
      </details>

      <form className="receipt" ref={receiptRef} data-testid="receipt-form" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <fieldset className="answer" data-testid="receipt-answer">
          <legend>Did you post it?</legend>
          {([["yes", "Yes, I posted it"], ["not_yet", "Not yet"], ["skip", "Skip this card"]] as const).map(([v, l]) => (
            <div key={v} className="answer-opt">
              <label className="radio-row"><input type="radio" name="answer" value={v} data-testid={`answer-${v}`} checked={answer === v}
                onChange={() => { setAnswer(v); setR({ ...r, attested: false, action: v === "skip" ? "skipped" : "acted" }); }} /> {l}</label>
              {v === "yes" && answer === "yes" && (
                <div className="confirm-yes" data-testid="confirm-yes">
                  <label className="radio-row attest"><input type="checkbox" data-testid="receipt-attest" checked={r.attested} onChange={(e) => setR({ ...r, attested: e.target.checked })} /> I confirm I posted this myself.</label>
                  <label>Win{" "}
                    <select data-testid="receipt-win" value={r.win_type ?? ""} onChange={(e) => {
                      const w = e.target.value || null;
                      setR({ ...r, win_type: w, criterion_hint: hintTouched ? r.criterion_hint : defaultHint(w) });
                    }}>
                      <option value="">none</option>
                      {WIN_TYPES.map((w) => <option key={w} value={w} disabled={w === "evidence_ab" && p.evidence_status === "soft_pending"}>{WIN_TYPE_LABEL[w] ?? w}</option>)}
                    </select>
                  </label>
                  {r.win_type && (
                    <>
                      <label htmlFor="ev-url">Public link to the reply/intro/citation</label>
                      <input id="ev-url" type="url" inputMode="url" required data-testid="receipt-evidence-url" placeholder="https://x.com/…/status/…"
                        value={r.evidence_url ?? ""} aria-invalid={evTouched && !!evProblem} aria-describedby="ev-url-msg"
                        onBlur={() => setEvTouched(true)} onChange={(e) => setR({ ...r, evidence_url: e.target.value })} />
                      <p id="ev-url-msg" className="plain-msg" data-testid="evidence-url-error">{evTouched && evProblem ? evProblem : ""}</p>
                      <label>Which O-1A criterion this might support{" "}
                        <select data-testid="receipt-criterion" value={r.criterion_hint ?? "none"} onChange={(e) => { setHintTouched(true); setR({ ...r, criterion_hint: e.target.value }); }}>
                          {CRITERION_HINTS.map((c) => <option key={c} value={c}>{CRITERION_LABEL[c]}</option>)}
                        </select>
                      </label>
                      <p className="muted small">A hint for your lawyer, not a legal call.</p>
                    </>
                  )}
                </div>
              )}
              {v === "skip" && answer === "skip" && (
                <label className="radio-row attest"><input type="checkbox" data-testid="receipt-attest" checked={r.attested} onChange={(e) => setR({ ...r, attested: e.target.checked })} /> I confirm I'm skipping this card.</label>
              )}
            </div>
          ))}
        </fieldset>
        <details className="disclosure">
          <summary>Optional: topic override</summary>
          <label>Confirmed topic{" "}
            <select data-testid="receipt-lens" value={r.confirmed_lens ?? ""} onChange={(e) => setR({ ...r, confirmed_lens: e.target.value || null })}>
              <option value="">same as opening topic ({p.scout_slug})</option>
              {CLOSED_INTERESTS.map((i) => <option key={i.slug} value={i.slug}>{i.slug}</option>)}
            </select>
          </label>
        </details>
        {receiptError && <p className="plain-msg" role="alert" data-testid="receipt-error">{receiptError}</p>}
        <button type="submit" className="primary" data-testid={busy ? "btn-pending" : "receipt-submit"} disabled={(answer !== "not_yet" && (!r.attested || !!evProblem)) || busy} aria-busy={busy}>
          {busy && <span className="spinner" aria-hidden="true" />}{busy ? "Recording…" : answer === "not_yet" ? "Keep it waiting" : "Confirm"}
        </button>
      </form>
    </aside>
  );
}
