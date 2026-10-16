import { useState } from "react";
import { api } from "../api/client";
import type { Asset } from "../api/types";
import { CLOSED_INTERESTS } from "../interestsSeed";

// Closed pick lists (docs/TAB-COPY.md, DA): no free-text surface, door or topic.
const SURFACES = ["arxiv", "github", "medium", "carta", "lab", "conference", "working_paper", "substack"] as const;
const DOORS = ["EconLLM", "Augusto-civic"] as const;

/** In-app "Add asset" form → POST /inventory. Every refusal comes back as a plain message from the API. */
export function AddAssetForm({ open, offline, onAdded, onError }: {
  open: boolean; offline: boolean; existing: Asset[]; onAdded: (a: Asset) => void; onError: (m: string) => void;
}) {
  const [f, setF] = useState({ title: "", url: "", surface: "", door: "", tone_hint: "", slugs: [] as string[] });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const missing = !f.title.trim() ? "Add a title." : !f.surface ? "Pick where it lives." : !f.door ? "Pick a voice."
    : !f.tone_hint.trim() ? "Say how drafts should sound." : f.slugs.length === 0 ? "Pick at least one topic." : null;
  const toggle = (s: string) => setF({ ...f, slugs: f.slugs.includes(s) ? f.slugs.filter((x) => x !== s) : [...f.slugs, s] });
  const submit = async () => {
    if (missing || busy) return;
    setBusy(true); setErr(null); const t0 = Date.now();
    try {
      const r = await api.POST("/inventory", { body: { title: f.title, url: f.url || null, surface: f.surface, door: f.door,
        tone_hint: f.tone_hint, slugs: f.slugs, evidence_grade: "B" } });
      if (r.data) { onAdded(r.data as Asset); setF({ title: "", url: "", surface: "", door: "", tone_hint: "", slugs: [] }); }
      else { const m = (r.error as { message?: string })?.message ?? "Couldn't add that asset."; setErr(m); onError(m); }
    } finally { setTimeout(() => setBusy(false), Math.max(0, 300 - (Date.now() - t0))); }
  };
  return (
    <details className="panel add-asset" open={open || undefined} data-testid="add-asset">
      <summary><h3 className="add-asset-title">Add an asset</h3></summary>
      <form className="scout-form" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <label>Title<input data-testid="aa-title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></label>
        <label>Link (optional)<input data-testid="aa-url" type="url" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} /></label>
        <label>Where it lives<select data-testid="aa-surface" value={f.surface} onChange={(e) => setF({ ...f, surface: e.target.value })}>
          <option value="">Pick one…</option>{SURFACES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}</select></label>
        <label>Voice<select data-testid="aa-door" value={f.door} onChange={(e) => setF({ ...f, door: e.target.value })}>
          <option value="">Pick one…</option>{DOORS.map((d) => <option key={d} value={d}>{d}</option>)}</select></label>
        <label>How drafts should sound<input data-testid="aa-tone" placeholder="e.g. rigorous but plain" value={f.tone_hint}
          onChange={(e) => setF({ ...f, tone_hint: e.target.value })} /></label>
        <fieldset className="toggle-chips" data-testid="aa-slugs"><legend>Topics (pick at least one)</legend>
          {CLOSED_INTERESTS.map((i) => {
            const on = f.slugs.includes(i.slug);
            return (
              <label key={i.slug} className={`tchip door-${i.door}${on ? " on" : ""}`} data-slug={i.slug}>
                <input type="checkbox" className="tchip-input" checked={on} onChange={() => toggle(i.slug)} />
                <span className="tchip-check" aria-hidden="true">{on ? "✓" : ""}</span>{i.slug}
              </label>);
          })}
        </fieldset>
        <button type="submit" className="primary" aria-describedby="aa-hint aa-error" data-testid={busy ? "btn-pending" : "aa-submit"} disabled={!!missing || busy || offline} aria-busy={busy}>
          {busy && <span className="spinner" aria-hidden="true" />}{busy ? "Adding…" : "Add asset"}</button>
        {(missing || offline) && <span className="muted" id="aa-hint" data-testid="aa-hint">{offline ? "API offline: start it on :8710" : missing}</span>}
        {err && <p className="error" role="alert" id="aa-error" data-testid="aa-error">{err}</p>}
      </form>
    </details>
  );
}
