import { useState } from "react";
import { S9_FACTORS, type Card } from "../api/types";
import { EvidenceLabel } from "./Chrome";
import { TracePanel } from "./TracePanel";
import { LANG_CHIP, LANG_TOOLTIP, langTraceLine, doorLabel, toneLabel, FACTOR_LABEL, WEIGHTS_BASIS, killText, killedLine, scoreWord, whyFits, NO_LENS_OWN_WORDS, NO_DRAFT_TOOLTIP, noDraftLine, stripCaveat, caveatIn, TEMPLATE_NO_DRAFT_LINE, COPY_WITH_CAVEAT_LABEL, COPY_WITH_CAVEAT_TOOLTIP } from "../copy";

const PROMO_TIP = "From a company account, or carries a product link or sign-up pitch. No draft prepared; reply only if it's worth it to you.";

export function KilledCard({ killId, reasons, assetTitle }: { killId: string; reasons: string[]; assetTitle?: string }) {
  return (
    <div className="card killed" data-testid="killed-card" data-kill={killId}>
      <p>{killedLine(killId)}{assetTitle ? <span className="muted"> (checked against {assetTitle})</span> : null}</p>
      {killId !== "link_only" && (
        <details><summary>Why?</summary>
          <span className="kill">kill: {killId}</span>
          {reasons.length > 1 && <span className="muted"> (+ {reasons.slice(1).join(", ")})</span>}
        </details>
      )}
    </div>
  );
}

function DoorBadge({ door }: { door: Card["door"] }) {
  return <span className={`door door-${door}`} data-testid="door-badge" data-door={door}>{doorLabel(door)}</span>;
}

/** Designer P1: no_lens with no draft → don't tease a draft; Open post is primary. Draft present → treat as copyable. */
function isNoLens(card: Card): boolean {
  return card.handoff_blocked === "no_lens" && !(card.draft && card.draft.trim());
}

export function ScoutCard({ card, onHandoff, onConfirm, onNotForMe, onLater, pendingUntil, blockedReason, busy, limitReached }: {
  card: Card;
  onHandoff?: (c: Card, draftText?: string) => void;
  onConfirm?: (c: Card) => void;
  onNotForMe?: (c: Card) => void;
  onLater?: (c: Card) => void;
  pendingUntil?: string;
  blockedReason?: string;
  busy?: boolean;
  /** Designer P1 #3: this outlet's daily reply budget is 0 left → copy only, no hand-off to X. */
  limitReached?: boolean;
}) {
  const a = card.asset;
  const civic = card.door === "Augusto-civic";
  const isOped = card.format === "op-ed" && card.outlet !== "x" && card.outlet !== "linkedin";
  const noLens = isNoLens(card);
  const blocked = blockedReason ?? (!noLens && card.handoff_blocked ? killText(card.handoff_blocked) : undefined);
  // Main copy never carries the caveat, even on old rows (API cleans too; this is the second line of defence).
  const cav = card.caveat ?? a.caveat ?? null;
  const cleaned = stripCaveat(card.draft, cav);
  const noDraft = !!card.no_draft || (!!(card.draft ?? "").trim() && (!cleaned || caveatIn(cleaned, cav)));
  const shownDraft = noDraft ? "" : cleaned;
  const noDraftText = card.no_draft_line || (noDraft ? TEMPLATE_NO_DRAFT_LINE : null);
  const withCaveat = !noDraft && cav && shownDraft ? `${shownDraft}\n\n${cav}` : null;
  const copyOff = noDraft || card.copy_enabled === false;
  const [draftText, setDraftText] = useState(shownDraft);
  const [copied, setCopied] = useState(false);
  const copyOnly = () => {
    void navigator.clipboard?.writeText(draftText.trim());
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };
  const outletName = card.outlet === "x" ? "X" : "LinkedIn";
  const primaryLabel = busy ? "Preparing…" : pendingUntil ? "Did you post it?" : `Copy reply & open on ${outletName}`;
  const postText = (card.post_text ?? "").trim();
  const author = card.author?.trim() || null;

  return (
    <article className={`card door-edge-${card.door}`} data-testid="card" data-card-id={card.card_id} data-door={card.door} data-nolens={noLens || undefined}>
      {/* 1. Source thread (quoted) — redesign source-first */}
      <blockquote className="post-quote" data-testid="post-quote">
        <div className="post-quote-meta row meta">
          {author && <span className="post-author" data-testid="post-author">{author}</span>}
          {card.age && <span className="post-age muted" data-testid="post-age">{card.age}</span>}
          <a className="text-btn" data-testid="post-link" href={card.url} target="_blank" rel="noopener noreferrer">Open post</a>
        </div>
        {postText ? (
          <p className="post-text" data-testid="post-text">{postText}</p>
        ) : (
          <p className="post-text muted" data-testid="post-text-missing">Post text unavailable</p>
        )}
      </blockquote>

      <header className="row meta card-meta">
        <DoorBadge door={card.door} />
        {isOped && <span className="chip chip-es" data-testid="es-oped-chip" lang="es">ES · op-ed</span>}
        <span>{outletName} · {card.move}</span>
        <span className={`pill ${card.T_status === "ok" ? "pill-fresh" : "pill-stale"}`}>{card.T_status === "ok" ? "Fresh" : "Stale"}</span>
        {pendingUntil && <span className="pill pill-await" data-testid="await-pill">Waiting for you · expires {pendingUntil}</span>}
      </header>

      {/* 2. Why it fits + claim + caveat (slug pill lives only on Work) */}
      <p className="why-fits" data-testid="why-fits">
        {whyFits(card)}
        {card.claim ? <> Your angle: <span data-testid="claim" lang={card.lang}>{card.claim}</span></> : null}
      </p>
      {a.caveat ? (
        <p className="caveat muted" data-testid="caveat">{a.caveat}</p>
      ) : null}
      <div className="row asset-line" data-testid="card-asset">
        {card.mode === "scoped" ? (
          <>
            <span data-testid="card-asset-title">{a.title}</span> ·{" "}
            <span data-testid="card-asset-type">{a.type}</span> ·{" "}
            <span data-testid="card-asset-door">{a.door}</span> ·{" "}
            <span className="tone" data-testid="card-asset-tone" title={a.tone_hint ?? undefined}>{toneLabel(a.tone)}</span>
          </>
        ) : (
          <span>profile-wide</span>
        )}{" "}
        · <EvidenceLabel asset={a} />
      </div>

      {/* 3. Draft — or no_lens own-words message */}
      {card.labels?.includes("brand_post") && (
        <span className="chip promo" data-testid="brand-chip" tabIndex={0} title={PROMO_TIP}
          aria-describedby={`promo-tip-${card.card_id}`}>
          Promotional
          <span id={`promo-tip-${card.card_id}`} className="sr-only">{PROMO_TIP}</span>
        </span>
      )}
      {card.labels?.includes("lang_capped") && (
        <span className="chip lang" data-testid="lang-chip" title={LANG_TOOLTIP}
              aria-describedby={`lang-tip-${card.card_id}`}>
          {LANG_CHIP}
          <span id={`lang-tip-${card.card_id}`} className="sr-only">{LANG_TOOLTIP}</span>
        </span>
      )}
      {card.labels?.includes("lang_capped") && langTraceLine(card.fit_trace?.lang) && (
        <p className="trace lang-trace" data-testid="lang-trace">{langTraceLine(card.fit_trace?.lang)}</p>
      )}
      {civic && card.source_chip && card.lang === "es" && (
        <span className="chip source" data-testid="source-chip">{card.source_chip}</span>
      )}
      {noLens ? (
        <p className="nolens-msg" data-testid="nolens-msg">{NO_LENS_OWN_WORDS}</p>
      ) : noDraft && noDraftText ? (
        <p className="muted small no-draft" data-testid="no-draft-line">{noDraftText}</p>
      ) : shownDraft ? (
        <label className="draft-edit">
          <span className="muted small">Your reply</span>
          <textarea
            className={`draft-area${civic ? " civic" : ""}`}
            data-testid="draft"
            lang={card.lang}
            rows={4}
            value={draftText}
            onChange={(e) => setDraftText(e.target.value)}
          />
        </label>
      ) : card.predraft?.code === "xbrief_declined" ? (
        <p className="muted small no-draft" data-testid="no-draft-declined" title={NO_DRAFT_TOOLTIP}>
          {noDraftLine(card.predraft?.decline_reason)}
        </p>
      ) : card.handoff_blocked ? null : (
        <p className="muted small" data-testid="draft-missing">Writing a draft…</p>
      )}

      {/* 4. Actions */}
      {onHandoff && (
        <div className="cta-row">
          {noLens ? (
            <>
              <a className="primary cta-link" data-testid="cta-open-post" href={card.url} target="_blank" rel="noopener noreferrer">Open post</a>
              {!pendingUntil && onNotForMe && (
                <button className="secondary small-btn" data-testid="cta-not-for-me" disabled={busy} onClick={() => onNotForMe(card)}>Not for me</button>
              )}
              {!pendingUntil && onLater && (
                <button className="text-btn" data-testid="cta-later" disabled={busy} onClick={() => onLater(card)}>Later</button>
              )}
            </>
          ) : pendingUntil && onConfirm ? (
            <>
              <button className="primary" data-testid="cta-confirm" onClick={() => onConfirm(card)}>{primaryLabel}</button>
              {onHandoff && <button className="text-btn" data-testid="cta-recopy" disabled={!!blocked || busy} onClick={() => onHandoff(card, draftText || undefined)}>Copy again</button>}
            </>
          ) : limitReached ? (
            <>
              <button className="secondary" data-testid="cta-copy-only" disabled={!!blocked || busy || copyOff || !draftText.trim()}
                aria-describedby={`lim-${card.card_id}`} onClick={copyOnly}>
                {copied ? "Copied" : "Copy reply"}
              </button>
              {!pendingUntil && onNotForMe && (
                <button className="secondary small-btn" data-testid="cta-not-for-me" disabled={busy} onClick={() => onNotForMe(card)}>Not for me</button>
              )}
              {!pendingUntil && onLater && (
                <button className="text-btn" data-testid="cta-later" disabled={busy} onClick={() => onLater(card)}>Later</button>
              )}
              <p className="muted small cta-limit" id={`lim-${card.card_id}`} data-testid="cta-limit">{outletName} limit reached for today</p>
            </>
          ) : (
            <>
              <button
                className="primary"
                data-testid={busy ? "btn-pending" : "cta-handoff"}
                disabled={!!blocked || busy || copyOff}
                aria-busy={busy}
                aria-describedby={blocked ? `blk-${card.card_id}` : undefined}
                onClick={() => onHandoff(card, draftText || undefined)}
              >
                {busy && <span className="spinner" aria-hidden="true" />}
                {primaryLabel}
              </button>
              {withCaveat && !copyOff && (
                <button className="text-btn" data-testid="cta-copy-with-caveat" title={COPY_WITH_CAVEAT_TOOLTIP}
                  disabled={busy} onClick={() => { void navigator.clipboard?.writeText(`${draftText.trim()}\n\n${cav}`); }}>
                  {COPY_WITH_CAVEAT_LABEL}
                </button>
              )}
              {!pendingUntil && onNotForMe && (
                <button className="secondary small-btn" data-testid="cta-not-for-me" disabled={busy} onClick={() => onNotForMe(card)}>Not for me</button>
              )}
              {!pendingUntil && onLater && (
                <button className="text-btn" data-testid="cta-later" disabled={busy} onClick={() => onLater(card)}>Later</button>
              )}
              {blocked && <p className="muted cta-blocked" id={`blk-${card.card_id}`} data-testid="cta-blocked" data-code={card.handoff_blocked ?? undefined}>{blocked}</p>}
            </>
          )}
        </div>
      )}

      {/* 5. Score row + §9 factors */}
      {card.rank_reason && (
        <div className={`rank-line tier-${card.rank_reason.tier}`} data-testid="rank-line" tabIndex={0}
          title={card.rank_reason.tooltip}>{card.rank_reason.text}</div>
      )}
      <div className="score-row" data-testid="score-row">
        <span className="score" data-testid="score" title={`Score = Fit, Urgency, Format fit, Evidence, Voice match, minus Effort cost.\n${WEIGHTS_BASIS}`}>
          <span className="score-label">{scoreWord(card.S)}</span> · {Math.round(card.S)}
        </span>
        {card.likes_info != null && (
          <span className="likes-info" data-testid="likes-info">{card.likes_info} likes (not used in score)</span>
        )}
      </div>
      <dl className="s9" data-testid="s9-strip">
        {S9_FACTORS.map((f) => {
          const v = card.factors[f] ?? 0;
          const pct = Math.max(0, Math.min(1, v)) * 100;
          return (
            <div key={f} className="factor" data-testid={`s9-${f}`}>
              <dt data-factor={f}>{FACTOR_LABEL[f]}</dt>
              <dd>{v.toFixed(2)}</dd>
              <div className="s9-bar" aria-hidden="true">
                <span className={`s9-bar-fill${f === "EffortPenalty" ? " penalty" : ""}`} style={{ width: `${pct}%` }} />
              </div>
            </div>
          );
        })}
      </dl>
      {onHandoff && <TracePanel cardId={card.card_id} />}
    </article>
  );
}
