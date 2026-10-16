import { useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import { WIN_COLUMNS, type Asset, type Card, type Handoff, type PendingHandoff, type QueueView, type RecommendResult, type StatusView, type WinRow } from "./api/types";
import { Banner, DoorLegend, EvidenceLabel, FooterInvariants, FilterChips, StatusLine } from "./components/Chrome";
import { ActionButton, ApiStatus, EmptyState, Onboarding, Skeleton, Toasts, useHealth, useToasts } from "./components/Feedback";
import { HandoffPanel, expiresIn, type ReceiptDraft } from "./components/HandoffPanel";
import { KilledCard, ScoutCard } from "./components/ScoutCard";
import { KILL_TEXT as KILL_TEXT_KEYS, LINK_ONLY_MSG, WIN_LABEL, WIN_TYPE_LABEL, kindLabel, killText, TAB_COPY, toneLabel, topicLabel } from "./copy";
import { AddAssetForm } from "./components/AddAssetForm";

type View = "today" | "work" | "wins";
const TAB_LABEL: Record<View, string> = { today: "Today", work: "Work", wins: "Wins" };
const OB_KEY = "ms.onboarding.done";
const errText = (e: unknown) => {
  const b = e as { code?: string; message?: string; error?: string } | undefined;
  const code = b?.code ?? b?.error;
  if (code === "link_only") return LINK_ONLY_MSG;
  if (code && code in KILL_TEXT_KEYS) return killText(code);
  return b?.message ?? "Something went wrong talking to the API.";
};
const errCode = (e: unknown) => {
  const b = e as { code?: string; error?: string } | undefined;
  return b?.code ?? b?.error ?? "unknown";
};

export default function App() {
  const [view, setView] = useState<View>("today");
  const [inventory, setInventory] = useState<Asset[]>([]);
  const [assetId, setAssetId] = useState<string | null>(null);
  const [queue, setQueue] = useState<QueueView>({ selected_asset: null, cap: {}, cards: [] });
  const [status, setStatus] = useState<StatusView | null>(null);
  const [result, setResult] = useState<RecommendResult | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [handoff, setHandoff] = useState<Handoff | null>(null);
  const [atReceipt, setAtReceipt] = useState(false);
  const [receiptErr, setReceiptErr] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, string>>({});
  const [waiting, setWaiting] = useState<PendingHandoff[]>([]);
  const [sealing, setSealing] = useState<string | null>(null);
  const [wins, setWins] = useState<WinRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [showGuide, setShowGuide] = useState(() => { try { return !localStorage.getItem(OB_KEY); } catch { return true; } });
  const [checkOpen, setCheckOpen] = useState(false);
  const [laterCards, setLaterCards] = useState<Card[]>([]);
  const [outletFilter, setOutletFilter] = useState<"all" | "x" | "linkedin">("all");
  const [paste, setPaste] = useState({ url: "", snippet: "", outlet: "x" as "x" | "linkedin" });
  const snippetRef = useRef<HTMLTextAreaElement | null>(null);
  const health = useHealth();
  const { toasts, push: pushToast, dismiss } = useToasts();
  const drawerOpen = useRef(false);
  drawerOpen.current = !!handoff;
  const push: typeof pushToast = (t) => { if (!drawerOpen.current) pushToast(t); };
  const openHandoff = (h: Handoff | null, receipt = false) => { setReceiptErr(null); setAtReceipt(receipt); setHandoff(h); };
  const offline = health === "offline";
  const selected = inventory.find((a) => a.asset_id === assetId) ?? null;

  const refresh = async () => {
    const [inv, q, w, hp, st] = await Promise.all([
      api.GET("/inventory"),
      api.GET("/queue", { params: { query: { asset_id: assetId } } }),
      api.GET("/wins"),
      api.GET("/handoff", { params: { query: { status: "pending" } } }),
      api.GET("/status"),
    ]);
    const ph = Array.isArray(hp.data) ? (hp.data as PendingHandoff[]) : [];
    setWaiting(ph);
    setPending(Object.fromEntries(ph.map((h) => [h.payload.scout_card_id, h.expires_at])));
    setInventory((inv.data as Asset[]) ?? []);
    if (q.data) {
      const qv = q.data as QueueView;
      const hasPost = (c: Card) => !!(c.post_text && c.post_text.trim());
      const cards = (assetId ? qv.cards.filter((c) => c.asset.asset_id === assetId) : qv.cards).filter(hasPost);
      const later = (qv.later ?? []).filter((c) => (!assetId || c.asset.asset_id === assetId) && hasPost(c));
      setQueue({ ...qv, cards });
      setLaterCards(later);
    }
    setWins((w.data as WinRow[]) ?? []);
    if (st.data) setStatus(st.data as StatusView);
    return q.data as QueueView | undefined;
  };
  useEffect(() => {
    refresh()
      .catch((e) => { push({ kind: "error", text: "Couldn't load your data. Is the API running on :8710?", details: String(e) }); })
      .finally(() => setLoaded(true));
  }, [assetId]);

  const pick = (id: string | null) => {
    setAssetId(id);
    const a = inventory.find((x) => x.asset_id === id);
    push({ kind: "success", text: a ? `Showing openings for: ${a.title}.` : "Showing openings across all work." });
  };
  const closeGuide = () => { setShowGuide(false); try { localStorage.setItem(OB_KEY, "1"); } catch { /* ignore */ } };

  const checkPost = async () => {
    setCheckError(null);
    setResult(null);
    const r = await api.POST("/recommend", { params: { query: { asset_id: assetId } }, body: { url: paste.url, snippet: paste.snippet, outlet: paste.outlet, age_hours: 12 } });
    const code = errCode(r.error);
    const fail = (msg: string) => {
      setCheckError(msg);
      // Designer P1: message under Text field + focus it; ActionButton clears pending in finally
      snippetRef.current?.focus();
    };
    if (r.error && !(r.error as RecommendResult).status) {
      if (code === "link_only" || (r.response && r.response.status === 422 && code === "link_only")) {
        fail(LINK_ONLY_MSG); return;
      }
      const body = r.error as { code?: string; error?: string; message?: string };
      if (body?.code === "link_only" || body?.error === "link_only") {
        fail(LINK_ONLY_MSG); return;
      }
      fail(errText(r.error)); return;
    }
    const res = (r.data ?? r.error) as RecommendResult;
    setResult(res);
    if (res.card && res.ok) push({ kind: "success", text: `Opening added (Score ${Math.round(res.card.S)}).` });
    await refresh();
  };

  const startHandoff = async (c: Card, draftText?: string) => {
    setSealing(c.card_id);
    const t0 = Date.now();
    try {
      const r = await api.POST("/handoff", { body: { card_id: c.card_id } });
      if (r.data) {
        const h = r.data as Handoff;
        const text = (draftText ?? c.draft ?? "").trim();
        if (text) {
          try { await navigator.clipboard.writeText(text); } catch { /* copy best-effort */ }
          try {
            const a = document.createElement("a");
            a.href = c.url; a.target = "_blank"; a.rel = "noopener noreferrer";
            a.click();
          } catch { /* ignore */ }
          setPending((p) => ({ ...p, [c.card_id]: h.payload.expires_at }));
          push({ kind: "success", text: "Reply copied. Confirm when you're back." });
          refresh();
        } else {
          openHandoff(h);
          setPending((p) => ({ ...p, [c.card_id]: h.payload.expires_at }));
          refresh();
        }
      } else push({ kind: "error", text: errText(r.error), details: errCode(r.error) });
    } finally { setTimeout(() => setSealing(null), Math.max(0, 300 - (Date.now() - t0))); }
  };

  const notForMe = async (c: Card) => {
    setSealing(c.card_id);
    try {
      const r = await api.POST("/handoff", { body: { card_id: c.card_id } });
      if (!r.data) { push({ kind: "error", text: errText(r.error), details: errCode(r.error) }); return; }
      const h = r.data as Handoff;
      await api.POST("/handoff/receipt", { body: {
        handoff_id: h.payload.handoff_id, seal: h.seal, pause_checksum: h.payload.pause_checksum,
        attested: true, attested_by: "user", action: "skipped", confirmed_lens: null, win_type: null,
        evidence_url: null, criterion_hint: null } });
      push({ kind: "success", text: "Got it — won't show this one again." });
      await refresh();
    } finally { setSealing(null); }
  };

  const later = async (c: Card) => {
    setSealing(c.card_id);
    try {
      const r = await api.POST("/later", { body: { card_id: c.card_id } } as never);
      if (r.error) { push({ kind: "error", text: errText(r.error), details: errCode(r.error) }); return; }
      push({ kind: "success", text: "Saved for later (24h)." });
      await refresh();
    } finally { setSealing(null); }
  };

  const sendReceipt = async (d: ReceiptDraft) => {
    if (!handoff) return;
    const r = await api.POST("/handoff/receipt", { body: {
      handoff_id: handoff.payload.handoff_id, seal: handoff.seal, pause_checksum: handoff.payload.pause_checksum,
      attested: d.attested, attested_by: "user", action: d.action, confirmed_lens: d.confirmed_lens, win_type: d.win_type,
      evidence_url: d.evidence_url ?? null, criterion_hint: d.criterion_hint ?? null } });
    if (r.error) { setReceiptErr(errText(r.error)); return; }
    setHandoff(null); drawerOpen.current = false;
    pushToast({ kind: "success", text: d.win_type ? "Win recorded." : d.action === "skipped" ? "Skipped." : "Saved." });
    setPending((p) => { const n = { ...p }; delete n[handoff.payload.scout_card_id]; return n; });
    refresh();
  };
  const confirmCard = (c: Card) => {
    const h = waiting.find((w) => w.payload.scout_card_id === c.card_id);
    if (h) openHandoff(h, true);
  };

  const offlineWhy = offline ? "API offline: start it on :8710" : undefined;
  const openings = queue.cards.filter((c) => outletFilter === "all" || c.outlet === outletFilter);
  const savedLater = laterCards.filter((c) => outletFilter === "all" || c.outlet === outletFilter);
  const weekWins = wins.length; // strip count; date filter left for later when API exposes it

  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <Banner />
      <div className="topbar">
        <nav data-testid="nav" aria-label="Main">
          {(["today", "work", "wins"] as View[]).map((t) => (
            <button key={t} className={view === t ? "tab on" : "tab"} aria-current={view === t ? "page" : undefined} aria-label={TAB_LABEL[t]} onClick={() => setView(t)}>
              {TAB_LABEL[t]}
              {t === "today" && <span className="nav-count" data-testid="nav-count-today">{openings.length}</span>}
              {t === "wins" && <span className="nav-count" data-testid="nav-count-wins">{wins.length}</span>}
            </button>
          ))}
        </nav>
        <div className="topbar-right">
          <ApiStatus health={health} />
          <button className="text-btn how" data-testid="how-it-works" aria-label="How it works" onClick={() => setShowGuide(true)}><span className="how-long">How it works</span><span className="how-short" aria-hidden="true">?</span></button>
        </div>
      </div>
      {showGuide && <Onboarding onStart={() => { closeGuide(); setView("today"); }} onDismiss={closeGuide} />}
      {view === "today" && <FilterChips asset={selected} inventory={inventory} onPick={pick} outlet={outletFilter} onOutlet={setOutletFilter} />}

      <main id="main">
      {view === "today" && (
        <section data-testid="today">
          <StatusLine status={status} cap={queue.cap} replies={queue.replies_today} openings={loaded ? openings.length : undefined} />
          <p className="tab-purpose sr-only" data-testid="tab-purpose">{TAB_COPY.today.purpose}</p>

          {waiting.length > 0 && (
            <div className="panel waiting" data-testid="waiting-receipts">
              <h3>Waiting for you</h3>
              <ul>{waiting.map((h) => (
                <li key={h.payload.handoff_id} data-testid="waiting-item">
                  <span>{h.asset_title} · {h.payload.door === "EconLLM" ? "Research voice" : "Civic voice"}</span>
                  <span className="muted"> expires {expiresIn(h.expires_at)}</span>{" "}
                  <button className="text-btn" data-testid="waiting-open" onClick={() => openHandoff(h, true)}>Did you post it?</button>
                </li>))}</ul>
            </div>
          )}

          <h2 className="section-title">Openings</h2>
          {!loaded ? <Skeleton /> : openings.length === 0 ? (
            <EmptyState text={TAB_COPY.today.empty} />
          ) : openings.map((c) => (
            <ScoutCard key={c.card_id} card={c} onHandoff={startHandoff} onConfirm={confirmCard}
              onNotForMe={notForMe} onLater={later} busy={sealing === c.card_id}
              limitReached={queue.replies_today?.[c.outlet]?.left === 0}
              blockedReason={offlineWhy} pendingUntil={pending[c.card_id] ? expiresIn(pending[c.card_id]) : undefined} />
          ))}
          {savedLater.length > 0 && (
            <details className="later-strip" data-testid="later-strip">
              <summary>Saved for later ({savedLater.length})</summary>
              {savedLater.map((c) => (
                <ScoutCard key={c.card_id} card={c} onHandoff={startHandoff} onConfirm={confirmCard}
                  onNotForMe={notForMe} onLater={later} busy={sealing === c.card_id}
              limitReached={queue.replies_today?.[c.outlet]?.left === 0}
                  blockedReason={offlineWhy} pendingUntil={pending[c.card_id] ? expiresIn(pending[c.card_id]) : undefined} />
              ))}
            </details>
          )}

          <details className="check-post" data-testid="check-post" open={checkOpen || undefined} onToggle={(e) => setCheckOpen((e.target as HTMLDetailsElement).open)}>
            <summary>Check a post</summary>
            <p className="muted small">Paste something you found yourself. If you only paste a link, paste the post text too.</p>
            <form className="scout-form" onSubmit={(e) => e.preventDefault()}>
              <label>Link<input data-testid="paste-url" type="url" placeholder="https://x.com/…/status/…" value={paste.url} onChange={(e) => setPaste({ ...paste, url: e.target.value })} /></label>
              <label>Text (paste the thread)
                <textarea ref={snippetRef} data-testid="paste-snippet" placeholder="e.g. “LLM survey respondents only look like WEIRD samples…”" value={paste.snippet} onChange={(e) => { setPaste({ ...paste, snippet: e.target.value }); if (checkError) setCheckError(null); }} />
                {checkError && <p className="field-error" role="alert" data-testid="link-only-error">{checkError}</p>}
              </label>
              <fieldset className="segmented" data-testid="paste-outlet"><legend>Where you saw it</legend>
                <div className="seg-row">
                  {(["x", "linkedin"] as const).map((o) => (
                    <button type="button" key={o} className={paste.outlet === o ? "seg on" : "seg"} data-testid={`outlet-${o}`}
                      aria-pressed={paste.outlet === o} onClick={() => setPaste({ ...paste, outlet: o })}>{o === "x" ? "X" : "LinkedIn"}</button>
                  ))}
                </div>
              </fieldset>
              <ActionButton label="Check" pendingLabel="Checking…" testId="scout-btn" onClick={checkPost}
                disabled={offline || !paste.url} disabledReason={offlineWhy ?? "Add a link first"} />
            </form>
            {result && <ResultView r={result} asset={selected} onPick={pick} onHandoff={startHandoff} />}
          </details>

          <div className="wins-strip" data-testid="wins-strip">
            <button className="text-btn" onClick={() => setView("wins")}>
              This week: {weekWins === 1 ? "1 reply posted" : `${weekWins} replies posted`} · view Wins
            </button>
          </div>
        </section>
      )}

      {view === "work" && (
        <section data-testid="work">
          <p className="tab-purpose" data-testid="tab-purpose">{TAB_COPY.work.purpose}</p>
          <DoorLegend />
          {!loaded ? <Skeleton /> : inventory.length === 0 ? (
            <EmptyState text={TAB_COPY.work.empty} />
          ) : (
            <div className="table-wrap"><table className="inv"><thead><tr><th>Asset</th><th>Kind</th><th>Voice</th><th>Topics</th><th>Evidence</th><th><span className="sr-only">Action</span></th></tr></thead>
              <tbody>{inventory.map((a) => (
                <tr key={a.asset_id} className={a.asset_id === assetId ? "sel" : ""} data-door={a.door}>
                  <td>{a.title}<div className="muted small" title={a.tone_hint ?? undefined} data-testid="asset-tone">{toneLabel(a.tone)}</div></td><td data-testid="asset-kind" title={a.type}>{kindLabel(a.type)}</td>
                  <td><span className={`door door-${a.door}`}>{a.door === "EconLLM" ? "Research voice" : "Civic voice"}</span></td>
                  <td className="work-topics" data-testid="work-topics">{a.slugs.map((s) => (
                    <code key={s} className="slug-pill" data-testid="work-slug" title={topicLabel(s)}>{s}</code>
                  ))}</td>
                  <td><EvidenceLabel asset={a} /></td>
                  <td>{a.asset_id === assetId ? <span className="muted">Showing</span> :
                    <button className="secondary small-btn nowrap" data-testid="promote" onClick={() => { pick(a.asset_id); setView("today"); }}>Show on Today</button>}</td>
                </tr>))}</tbody></table></div>
          )}
          <AddAssetForm open={loaded && inventory.length === 0} offline={offline} existing={inventory}
            onAdded={(a) => { push({ kind: "success", text: `Added ${a.title}.` }); refresh(); }}
            onError={(m) => push({ kind: "error", text: m })} />
        </section>
      )}

      {view === "wins" && (
        <section data-testid="wins">
          <p className="tab-purpose" data-testid="tab-purpose">{TAB_COPY.wins.purpose}</p>
          {!loaded ? <Skeleton /> : wins.length === 0 ? (
            <EmptyState text={TAB_COPY.wins.empty} />
          ) : null}
          <div className="table-wrap" hidden={wins.length === 0}><table data-testid="wins-table"><thead><tr>{WIN_COLUMNS.map((c) => <th key={c} data-col={c}>{WIN_LABEL[c]}</th>)}</tr></thead>
            <tbody>{wins.map((w, i) => <tr key={i}>{WIN_COLUMNS.map((c) => <td key={c}>{winCell(w, c, inventory)}</td>)}</tr>)}</tbody></table></div>
        </section>
      )}
      </main>

      {handoff && <div className="backdrop" aria-hidden="true" onClick={() => setHandoff(null)} />}
      {handoff && <HandoffPanel handoff={handoff} onReceipt={sendReceipt} onClose={() => setHandoff(null)}
        key={handoff.payload.handoff_id} startAtReceipt={atReceipt} receiptError={receiptErr}
        assetTitle={inventory.find((a) => a.asset_id === handoff.payload.asset_id)?.title} />}
      <Toasts toasts={toasts} onDismiss={dismiss} />
      <FooterInvariants />
    </div>
  );
}

function winCell(w: WinRow, c: (typeof WIN_COLUMNS)[number], inv: Asset[]) {
  const v = w[c];
  if (c === "asset_id") { const a = inv.find((x) => x.asset_id === v); return <span title={v ?? ""}>{a?.title ?? v ?? ""}</span>; }
  if (c === "slug") return <code className="slug-pill">{v}</code>;
  if (c === "outlet") return v === "x" ? "X" : v === "linkedin" ? "LinkedIn" : v ?? "";
  if (c === "win_type") return WIN_TYPE_LABEL[v as string] ?? v;
  return v ?? "";
}

export function ResultView({ r, asset, onPick, onHandoff }: { r: RecommendResult; asset?: Asset | null; onPick: (id: string) => void; onHandoff: (c: Card) => void }) {
  let body;
  if (r.status === "killed") body = <KilledCard killId={r.kill_id ?? "killed"} reasons={r.kill_reasons} assetTitle={asset?.title} />;
  else if (r.status === "asset_pick_required")
    body = (
      <div className="panel" data-testid="asset-pick">
        <p>This fits more than one of your assets. Which one are you promoting?</p>
        <div className="row">{(r.asset_options ?? []).map((a) => <button key={a.asset_id} className="secondary" onClick={() => onPick(a.asset_id)}>{a.title}</button>)}</div>
      </div>
    );
  else if (r.card) body = (
    <>
      <p className="outcome-line">{r.replaced_card_id ? `Added. It bumped a weaker card (now Score ${Math.round(r.card.S)}).` : "Added to Today."}</p>
      <ScoutCard card={r.card} onHandoff={r.ok ? onHandoff : undefined} />
    </>
  );
  else body = <p>Scouter couldn't score this. <details><summary>Details</summary><code>{r.status}</code></details></p>;
  return <div className="scout-outcome" data-testid="scout-outcome" data-status={r.status}>{body}</div>;
}
