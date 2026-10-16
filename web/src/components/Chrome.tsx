import type { Asset, ReplyBudget } from "../api/types";
import { BANNER_TEXT, doorLabel, toneLabel } from "../copy";

// Locked invariant copy — redesign approval 2026-10-09 (BUILD-LOG). Exact string; Adversarial/Marketing tests cite it.
export function Banner() {
  return (
    <div className="banner" data-testid="banner" role="note">
      {BANNER_TEXT}
    </div>
  );
}

function repliesLeft(raw: string | undefined): { left: number; max: number } {
  const [usedS, maxS] = (raw ?? "0/7").split("/");
  const used = Number(usedS) || 0;
  const max = Number(maxS) || 7;
  return { left: Math.max(0, max - used), max };
}

/** Replies left today for an outlet: the API's daily budget when present, else the legacy n/7 string. */
export function budgetFor(outlet: string, cap?: Record<string, string>, replies?: Record<string, ReplyBudget>): { left: number; max: number } {
  const b = replies?.[outlet];
  if (b) return { left: Math.max(0, b.left), max: b.max };
  return repliesLeft(cap?.[outlet]);
}

/** Reply-budget pills — live in StatusLine (Designer P1 mobile: not in the tab row). */
export function CapMeters({ cap, replies }: { cap: Record<string, string>; replies?: Record<string, ReplyBudget> }) {
  const x = budgetFor("x", cap, replies);
  const li = budgetFor("linkedin", cap, replies);
  return (
    <span className="caps-inline" data-testid="cap-meters">
      X: {x.left} of {x.max} left · LinkedIn: {li.left} of {li.max}
    </span>
  );
}

export function DoorLegend() {
  return (
    <div className="legend" data-testid="door-legend">
      <span className="door door-EconLLM" title="Claim-source label, not org ownership">Research voice</span> = research ·{" "}
      <span className="door door-Augusto-civic" title="Claim-source label, not org ownership">Civic voice</span> = civic (Spanish only for Argentine op-eds)
    </div>
  );
}

export function FooterInvariants() {
  return (
    <footer className="footer" data-testid="footer-invariants">
      likes never drive S · Fit empty → 0 → no card · Evidence C out · cap 7/outlet
    </footer>
  );
}

export function EvidenceLabel({ asset }: { asset: Pick<Asset, "evidence_grade" | "evidence_status" | "oped_status"> }) {
  if (asset.evidence_status === "soft_pending")
    return (
      <span className="evidence evidence-soft" data-testid="evidence" data-evidence="soft_pending">
        <span title={`Counts as soft until the op-ed is out${asset.oped_status ? ` (op-ed ${asset.oped_status})` : ""}.`}>Evidence {asset.evidence_grade} · pending</span>
      </span>
    );
  const cls = asset.evidence_grade === "A" ? "evidence-a" : asset.evidence_grade === "B" ? "evidence-b" : "evidence-out";
  return (
    <span className={`evidence ${cls}`} data-testid="evidence" data-evidence={asset.evidence_status}>
      Evidence {asset.evidence_grade}
    </span>
  );
}

/** Short chip label for an asset (Designer Q2). */
export function shortAssetName(a: Asset): string {
  const t = a.title.split(/[—–-]/)[0].trim();
  if (t.length <= 22) return t;
  return t.slice(0, 20).trimEnd() + "…";
}

/** Filter chips: All work + assets; optional X/LinkedIn pair after a divider. */
export function FilterChips({
  asset, inventory, onPick, outlet, onOutlet,
}: {
  asset: Asset | null;
  inventory: Asset[];
  onPick: (id: string | null) => void;
  outlet?: "all" | "x" | "linkedin";
  onOutlet?: (o: "all" | "x" | "linkedin") => void;
}) {
  return (
    <div className="filter-chips sticky" data-testid="selected-asset" data-mode={asset ? "scoped" : "general"}>
      <div className="chip-scroll" data-testid="filter-chips" role="toolbar" aria-label="Filter openings">
        <button type="button" className={`fchip${!asset ? " on" : ""}`} data-testid="chip-all" aria-pressed={!asset} onClick={() => onPick(null)}>All work</button>
        {inventory.map((a) => (
          <button key={a.asset_id} type="button" className={`fchip${asset?.asset_id === a.asset_id ? " on" : ""}`}
            data-testid={`chip-asset-${a.asset_id}`} aria-pressed={asset?.asset_id === a.asset_id}
            title={a.title} onClick={() => onPick(a.asset_id)}>{shortAssetName(a)}</button>
        ))}
        {onOutlet && (
          <>
            <span className="chip-divider" aria-hidden="true" />
            <button type="button" className={`fchip${outlet === "x" ? " on" : ""}`} data-testid="chip-outlet-x"
              aria-pressed={outlet === "x"} onClick={() => onOutlet(outlet === "x" ? "all" : "x")}>X</button>
            <button type="button" className={`fchip${outlet === "linkedin" ? " on" : ""}`} data-testid="chip-outlet-linkedin"
              aria-pressed={outlet === "linkedin"} onClick={() => onOutlet(outlet === "linkedin" ? "all" : "linkedin")}>LinkedIn</button>
          </>
        )}
      </div>
      {asset && (
        <span className="sa-meta sr-only" data-testid="sa-title">{asset.title}</span>
      )}
      {/* Keep legacy test hooks for tone/door when scoped */}
      {asset && (
        <span className="sr-only">
          <span data-testid="sa-type">{asset.type}</span>
          <span className={`door door-${asset.door}`} data-testid="sa-door">{doorLabel(asset.door)}</span>
          <code className="slug-mono" data-testid="sa-slug">{asset.primary_slug}</code>
          <span className="sa-tone" data-testid="sa-tone" title={asset.tone_hint ?? undefined}>{toneLabel(asset.tone)}</span>
        </span>
      )}
    </div>
  );
}

/** Sticky filter strip — chips on Today; promoting picker kept for scope (Work). */
export function SelectedAsset({ asset, inventory, onPick }: { asset: Asset | null; inventory?: Asset[]; onPick?: (id: string | null) => void }) {
  if (onPick && inventory) {
    return <FilterChips asset={asset} inventory={inventory} onPick={onPick} />;
  }
  const picker = onPick && (
    <label className="promoting">
      <span>Showing:</span>{" "}
      <select data-testid="asset-select" value={asset?.asset_id ?? ""} onChange={(e) => onPick(e.target.value || null)}>
        <option value="">All work</option>
        {(inventory ?? []).map((a) => <option key={a.asset_id} value={a.asset_id}>{a.title}</option>)}
      </select>
    </label>
  );
  if (!asset)
    return (
      <div className="selected sticky" data-testid="selected-asset" data-mode="general">
        {picker ?? <>Showing: <strong>All work</strong></>}
        <span className="muted"> All your topics</span>
      </div>
    );
  const civic = asset.door === "Augusto-civic";
  return (
    <div className="selected sticky" data-testid="selected-asset" data-mode="scoped" lang={asset.lang}>
      {picker}
      <span className="sa-meta">
        {picker ? null : <>Showing: </>}<strong data-testid="sa-title" className={picker ? "sr-only" : ""}>{asset.title}</strong>{picker ? null : " · "}
        <span data-testid="sa-type">{asset.type}</span> ·{" "}
        <span className={`door door-${asset.door}`} data-testid="sa-door">
          {doorLabel(asset.door)}
          {civic && asset.format === "op-ed" && <span className="door-lang" lang="es">ES · op-ed</span>}
        </span>{" "}
        · <code className="slug-mono" data-testid="sa-slug">{asset.primary_slug}</code> ·{" "}
        <span className="sa-tone" data-testid="sa-tone" title={asset.tone_hint ?? undefined}>{toneLabel(asset.tone)}</span>
      </span>
    </div>
  );
}

/** Status line from GET /status — words, not dots. Caps live here (Designer P1). */
export function StatusLine({ status, cap, replies, openings }: {
  status: {
    x_last_checked: { sentence: string };
    drafting_ok: boolean;
    drafting_reason: string;
    queue_sentence: string;
  } | null;
  cap?: Record<string, string>;
  replies?: Record<string, ReplyBudget>;
  /** Cards actually shown in Openings (Later, empty-text and bot-author cards excluded); wins over the store count. */
  openings?: number;
}) {
  if (!status) return <p className="status-line muted" data-testid="status-line">Checking…</p>;
  // P2 quick: "Drafts ready · N openings" when drafting works
  const draftBit = status.drafting_ok ? "Drafts ready" : status.drafting_reason;
  const queueBit = openings != null ? `${openings} opening${openings === 1 ? "" : "s"}` : status.queue_sentence
    .replace(/(\d+) cards waiting in the queue\.?/i, (_, n) => `${n} openings`)
    .replace(/drafting works/i, "Drafts ready");
  return (
    <p className="status-line" data-testid="status-line" data-drafting={status.drafting_ok ? "ok" : "down"}>
      {status.x_last_checked.sentence} · {draftBit} · {queueBit}
      {cap ? <> · <CapMeters cap={cap} replies={replies} /></> : null}
    </p>
  );
}
