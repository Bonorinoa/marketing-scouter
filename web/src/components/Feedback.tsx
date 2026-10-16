import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";

export type Health = "checking" | "ok" | "slow" | "offline";

/** Polls /api/health every 15s; >2s = slow, error = offline. */
export function useHealth(intervalMs = 15000): Health {
  const [h, setH] = useState<Health>("checking");
  useEffect(() => {
    let alive = true;
    const ping = async () => {
      const t0 = performance.now();
      try {
        const r = await api.GET("/health");
        if (!alive) return;
        setH(!r.response.ok ? "offline" : performance.now() - t0 > 2000 ? "slow" : "ok");
      } catch { if (alive) setH("offline"); }
    };
    ping();
    const id = setInterval(ping, intervalMs);
    return () => { alive = false; clearInterval(id); };
  }, [intervalMs]);
  return h;
}

const HEALTH_TEXT: Record<Health, string> = {
  checking: "Checking API…", ok: "Connected", slow: "Slow", offline: "Offline: start the API on :8710",
};
export function ApiStatus({ health }: { health: Health }) {
  return (
    <span className={`api-status api-${health}`} data-testid="api-status" data-health={health} title={HEALTH_TEXT[health]}>
      <span className="dot" aria-hidden="true" />
      <span className="api-label">{HEALTH_TEXT[health]}</span>
    </span>
  );
}

export interface Toast { id: number; kind: "success" | "error"; text: string; details?: string }

export function Toasts({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  return (
    <div className="toasts" aria-live="polite" role="status">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.kind}`} data-testid="toast" data-kind={t.kind}>
          <span>{t.text}</span>
          {t.details && (
            <details className="toast-details"><summary>Details</summary><code>{t.details}</code></details>
          )}
          <button className="text-btn" aria-label="Dismiss" onClick={() => onDismiss(t.id)}>×</button>
        </div>
      ))}
    </div>
  );
}

export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const n = useRef(0);
  const dismiss = (id: number) => setToasts((ts) => ts.filter((t) => t.id !== id));
  const push = (t: Omit<Toast, "id">) => {
    const id = ++n.current;
    setToasts([{ ...t, id }]);
    setTimeout(() => dismiss(id), t.kind === "error" ? 8000 : 4000);
  };
  return { toasts, push, dismiss };
}

/** Button with pending state: verb-ing label + spinner, min 300ms so it doesn't flicker. */
export function ActionButton({ label, pendingLabel, onClick, disabled, disabledReason, className = "primary", testId }: {
  label: string; pendingLabel: string; onClick: () => Promise<unknown> | void; disabled?: boolean;
  disabledReason?: string; className?: string; testId?: string;
}) {
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { await onClick(); }
    finally { setBusy(false); } // clear pending immediately (Designer P1: stuck Checking…)
  };
  return (
    <button type="button" className={className} data-testid={busy ? "btn-pending" : testId} data-action={testId}
      disabled={busy || disabled} aria-busy={busy} title={disabled ? disabledReason : undefined} onClick={run}>
      {busy && <span className="spinner" aria-hidden="true" />}
      {busy ? pendingLabel : label}
    </button>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div data-testid="skeleton" aria-hidden="true">
      {Array.from({ length: rows }).map((_, i) => <div key={i} className="skeleton-row" />)}
    </div>
  );
}

export function EmptyState({ text, action, onAction }: { text: string; action?: string; onAction?: () => void }) {
  return (
    <div className="empty" data-testid="empty-state">
      <p>{text}</p>
      {action && <button className="secondary" onClick={onAction}>{action}</button>}
    </div>
  );
}

export function Onboarding({ onStart, onDismiss }: { onStart: () => void; onDismiss: () => void }) {
  return (
    <section className="onboarding" data-testid="onboarding" aria-labelledby="ob-title">
      <h2 id="ob-title">Find the right conversations for your work.</h2>
      <ol>
        <li><strong>Openings show up on Today.</strong> Each card has the post, why it fits, and a draft ready to edit.</li>
        <li><strong>Edit, copy, and open the post.</strong> You share the reply yourself — this app never does.</li>
        <li><strong>Confirm a Win</strong> when you're back, with the public link to what you shared.</li>
      </ol>
      <p className="muted">Suggests only. You post everything yourself.</p>
      <p className="muted small" data-testid="invariants">Likes never change a card's Score. A card needs at least one matching topic. Weak evidence never reaches Today. At most 7 cards per outlet.</p>
      <div className="row">
        <button className="primary" onClick={onStart}>Got it — show Today</button>
        <button className="text-btn" onClick={onDismiss}>Got it</button>
      </div>
    </section>
  );
}
