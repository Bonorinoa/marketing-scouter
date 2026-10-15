// Marketing Scouter front end. Vanilla JS, no build step, no framework.
// All dynamic text goes through esc() before it reaches innerHTML.
// Talks only to the local API (same origin). There is no code path that sends anything anywhere:
// "Copy" puts text on your clipboard; you paste it yourself.

const PANELS = {
  "op-eds":     { n: "01", title: "Op-eds",     sub: "La Nación · La Gaceta · LA Times", kind: "Letter or op-ed pitch", unit: "words", cap: 200 },
  "trends":     { n: "02", title: "Trends",     sub: "Hacker News · NBER · blogs",       kind: "Post for LinkedIn or X", unit: "chars", cap: 1200 },
  "commentary": { n: "03", title: "Commentary", sub: "Reddit · Hacker News threads",     kind: "Reply to a thread",      unit: "words", cap: 200, floor: 80 },
};
const ORDER = Object.keys(PANELS);
const LANG = { es: "Español", en: "English" };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const S = { state: null, items: {}, floor: 0.15, lens: {}, cur: null, drafts: [], viewing: null, dirty: false, busy: false };

// ───────── helpers ─────────
async function api(path, body) {
  let res;
  try {
    res = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch (e) {
    throw new Error("Cannot reach the scouter. Is `python3 -m scouter serve` running?");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function ago(value) {
  const t = typeof value === "number" ? value : Date.parse(value);
  if (!t) return "";
  const m = Math.max(0, (Date.now() - t) / 60000);
  if (m < 60) return `${Math.max(1, Math.round(m))}m`;
  if (m < 60 * 24) return `${Math.round(m / 60)}h`;
  return `${Math.round(m / 1440)}d`;
}

function toast(msg, isError = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (isError ? " error" : "");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.className = "toast"), isError ? 6500 : 3200);
}

function banner(html, isError = false) {
  const b = $("banner");
  if (!html) { b.hidden = true; return; }
  b.className = "banner" + (isError ? " error" : "");
  b.innerHTML = `<span>${html}</span><button type="button" aria-label="Dismiss">×</button>`;
  b.querySelector("button").onclick = () => (b.hidden = true);
  b.hidden = false;
}

const countWords = (s) => (s.trim() ? s.trim().split(/\s+/).length : 0);
const shortModel = (m) => (m || "").split("/").pop().replace(/^deepseek-/, "") || "model";

// ───────── data ─────────
async function loadState() {
  S.state = await api("/api/state");
  renderMasthead();
}

async function loadItems() {
  const lists = await Promise.all(ORDER.map((p) => api(`/api/candidates?panel=${p}&min=${S.floor}&limit=200`)));
  ORDER.forEach((p, i) => (S.items[p] = lists[i]));
  renderColumns();
}

// ───────── masthead ─────────
function renderMasthead() {
  const today = new Date().toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" });
  $("mastLeft").innerHTML = today;
  const total = Object.values(S.state.counts).reduce((a, b) => a + b, 0);
  const ls = S.state.last_scout;
  $("mastRight").innerHTML = `<b>${total}</b> items scored<br>` + (ls ? `last scout ${ago(ls.ts * 1000)} ago · $${(ls.cost_usd || 0).toFixed(4)}` : "never scouted");
}

// ───────── columns & cards ─────────
function renderColumns() {
  const wrap = $("columns");
  wrap.innerHTML = ORDER.map((p) => {
    const cfg = PANELS[p];
    const all = S.items[p] || [];
    const lenses = {};
    all.forEach((c) => (lenses[c.lens] = (lenses[c.lens] || 0) + 1));
    const sel = S.lens[p] || "";
    const shown = sel ? all.filter((c) => c.lens === sel) : all;
    const options = `<option value="">all interests (${all.length})</option>` +
      Object.entries(lenses).sort((a, b) => b[1] - a[1]).map(([l, n]) => `<option value="${esc(l)}" ${l === sel ? "selected" : ""}>${esc(l)} (${n})</option>`).join("");
    const body = shown.length
      ? shown.map(cardHtml).join("")
      : `<div class="empty">Nothing at relevance ${S.floor.toFixed(2)} or above${sel ? " for this interest" : ""}.<br>${all.length || sel ? "" : '<button class="btn primary" data-scout="' + p + '" type="button">Scout ' + cfg.title.toLowerCase() + "</button>"}</div>`;
    return `<section class="col" data-panel="${p}" aria-label="${cfg.title}">
      <div class="col-head">
        <div class="col-title"><span class="col-num">${cfg.n}</span><h2>${cfg.title}</h2><span class="col-count">${shown.length} shown</span></div>
        <div class="col-sub"><span>${cfg.sub}</span><select class="lens-filter" data-lens="${p}" aria-label="Filter ${cfg.title} by interest">${options}</select></div>
      </div>
      <div class="col-body">${body}</div>
    </section>`;
  }).join("");
  wrap.dataset.active = wrap.dataset.active || "op-eds";
  renderTabs();
}

function cardHtml(c) {
  const mark = c.status === "drafted" ? '<span class="mark drafted">Drafted</span>' : c.status === "approved" ? '<span class="mark approved">Approved ✓</span>' : "";
  const age = ago(c.published);
  const priv = c.personal > 0.3 ? ' <span class="private" title="A good reply might tempt you to share personal details">· private-info flag</span>' : "";
  return `<article class="card ${c.status === "approved" ? "is-done" : ""}" tabindex="0" role="button" data-id="${c.id}" aria-label="Open workspace: ${esc(c.title)}">
    <div class="card-top"><span class="src">${esc(sourceName(c))}${age ? " · " + age : ""}</span>${mark}</div>
    <h3>${esc(c.title)}</h3>
    <p>${esc(c.summary)}</p>
    <div class="card-foot">
      <div class="foot-rest"><span class="rel">${c.relevance.toFixed(2)}</span><span class="bar"><i style="width:${Math.round(c.relevance * 100)}%"></i></span><span class="lens">${esc(c.lens)}</span>${priv}</div>
      <div class="foot-hover"><div class="mini"><span><small>Best match</small> <b>${c.relevance.toFixed(2)}</b></span><span><em>${esc(c.lens)}</em></span></div><span class="open">Open workspace →</span></div>
    </div>
  </article>`;
}

const SOURCE_NAMES = { la_nacion_opinion: "La Nación · Opinión", la_nacion_economia: "La Nación · Economía", la_gaceta: "La Gaceta", la_times_opinion: "LA Times · Opinion",
  hn_trends: "Hacker News", nber_new: "NBER", gelman_blog: "Statistical Modeling", hn_front: "Hacker News", manual_x: "X post", manual: "Captured" };
function sourceName(c) {
  if (SOURCE_NAMES[c.source]) return SOURCE_NAMES[c.source];
  if (c.meta && c.meta.subreddit) return "r/" + c.meta.subreddit;
  return c.source;
}

function renderTabs() {
  const active = $("columns").dataset.active;
  $("panelTabs").innerHTML = ORDER.map((p) => `<button type="button" role="tab" data-tab="${p}" aria-selected="${p === active}">${PANELS[p].title} <span style="font-weight:400">${(S.items[p] || []).length}</span></button>`).join("");
}

// card spotlight follows the cursor
document.addEventListener("pointermove", (e) => {
  const card = e.target.closest && e.target.closest(".card");
  if (!card) return;
  const r = card.getBoundingClientRect();
  card.style.setProperty("--mx", `${e.clientX - r.left}px`);
  card.style.setProperty("--my", `${e.clientY - r.top}px`);
});

// ───────── workspace ─────────
async function openSpread(id, fromEl) {
  try {
    const c = await api(`/api/candidate?id=${id}`);
    S.cur = c;
    S.drafts = (c.drafts || []).map((d) => ({ ...d, flags: safeJson(d.flags) }));
    S.viewing = S.drafts.length ? S.drafts[0].id : null;
    S.dirty = false;
    renderSpread();
    const sp = $("spread");
    if (fromEl) {
      const r = fromEl.getBoundingClientRect();
      sp.style.setProperty("--from", `inset(${r.top}px ${innerWidth - r.right}px ${innerHeight - r.bottom}px ${r.left}px round 13px)`);
    }
    sp.hidden = false;
    sp.classList.remove("open");
    void sp.offsetWidth;
    sp.classList.add("open");
    document.body.style.overflow = "hidden";
    setTimeout(() => ($("take") && !S.drafts.length ? $("take").focus({ preventScroll: true }) : null), 650);
  } catch (e) { toast(e.message, true); }
}

function closeSpread() {
  if (S.dirty && !confirm("You have unsaved edits to this draft. Leave anyway?")) return;
  const sp = $("spread");
  sp.classList.remove("open");
  setTimeout(() => { sp.hidden = true; }, 560);
  S.cur = null;
  loadState().catch(() => {});
  loadItems().catch(() => {});
}

const safeJson = (s) => { try { return typeof s === "string" ? JSON.parse(s) : s || []; } catch { return []; } };
const viewingDraft = () => S.drafts.find((d) => d.id === S.viewing) || null;

function renderSpread() {
  const c = S.cur, cfg = PANELS[c.panel];
  $("spreadTitle").textContent = `${cfg.title} · workspace`;
  setState(c.status);
  renderLeft();
  renderRight();
}

function setState(status) {
  const el = $("spreadState");
  el.className = "spread-state " + status;
  el.textContent = status === "new" ? "Not drafted" : status === "drafted" ? "Drafted" : status === "approved" ? "Approved" : status;
}

function renderLeft() {
  const c = S.cur;
  const lang = LANG[c.meta && c.meta.lang];
  const age = ago(c.published);
  const pct = (v) => (v < 0.01 ? "<1%" : Math.round(v * 100) + "%");
  const sorted = Object.entries(c.scores).sort((a, b) => b[1] - a[1]);
  const d = viewingDraft();
  const flagsKey = (i) => `flag:${d.id}:${i}`;
  let suggestion = "";
  if (d && d.model !== "you (edited)") {
    const mine = (d.user_take || "").trim();
    const flags = d.flags || [];
    suggestion = `<div class="h3" style="margin-top:30px">Hermes's notes</div>
      <div class="suggestion">
        <div class="label">${mine ? "How Hermes used your take" : "Hermes chose this angle itself"}</div>
        ${mine ? `<blockquote class="takequote"><small>Your take</small>${esc(mine)}</blockquote>` : ""}
        <p>${esc(d.rationale)}</p>
        ${mine ? "" : '<p class="note">This is a suggestion, not your belief. Add your own take on the right and draft again to write from your position.</p>'}
        ${flags.length ? `<ul class="checks">${flags.map((f, i) => `<li><label><input type="checkbox" data-flag="${flagsKey(i)}" ${localStorage.getItem(flagsKey(i)) ? "checked" : ""}><span>${esc(f)}</span></label></li>`).join("")}</ul>` : ""}
      </div>`;
  }
  // the lens plus any other interest at 5% or more; the rest are summarised in one line
  const top = sorted.filter(([n, v], i) => i === 0 || v >= 0.05).slice(0, 4), rest = sorted.length - top.length;
  const why = `<div class="h3">Why this surfaced: match by interest</div>
    <table class="fit"><tbody>${top.map(([n, v]) => `<tr class="${n === c.lens ? "lensrow" : ""}"><td class="name">${esc(n)}</td><td class="meter"><span class="bar"><i style="width:${Math.round(v * 100)}%"></i></span></td><td class="pct">${pct(v)}</td></tr>`).join("")}</tbody></table>
    <p class="note">The ranker (Jev) asked one yes/no question per interest: is this item substantively about it? The best match, marked in red, is the lens it suggests writing through. ${rest > 0 ? `The remaining ${rest} score under 5%. ` : ""}It is a ranking, not a verdict.</p>
    ${c.personal > 0.3 ? `<div class="warn">Private-information flag (${c.personal.toFixed(2)}): a convincing reply might tempt you to share personal details. Keep it to ideas and evidence.</div>` : ""}`;
  const long = (c.summary || "").length > 330 && d;      // once a draft exists, the notes matter more than the abstract
  $("pageLeft").innerHTML = `<div class="sheet">
    <div class="eyebrow">${esc(sourceName(c))}${age ? `<span class="dot"></span><span class="dim">${age} ago</span>` : ""}${lang ? `<span class="chip">${lang}</span>` : ""}</div>
    <h2 class="headline">${esc(c.title)}</h2>
    <p class="lede ${long ? "clamped" : ""}" id="lede">${esc(c.summary) || '<em style="color:var(--muted)">The source gave no summary. Open the original to read it.</em>'}</p>
    ${long ? '<button class="more" id="moreBtn" type="button">Show the full summary</button>' : ""}
    <div class="original-wrap"><a class="original" href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">Read the original ↗</a></div>
    ${d ? `<div id="notes">${suggestion}</div>${why}` : why}</div>`;
  const more = $("moreBtn");
  if (more) more.onclick = () => { $("lede").classList.remove("clamped"); more.remove(); };
  $("pageLeft").querySelectorAll("[data-flag]").forEach((box) => box.addEventListener("change", () => {
    if (box.checked) localStorage.setItem(box.dataset.flag, "1"); else localStorage.removeItem(box.dataset.flag);
  }));
}

function ruleText(cfg) {
  if (cfg.unit === "chars") return `up to ${cfg.cap} characters`;
  return cfg.floor ? `${cfg.floor} to ${cfg.cap} words` : `up to ${cfg.cap} words`;
}

function renderRight() {
  const c = S.cur, cfg = PANELS[c.panel];
  const d = viewingDraft();
  const lang = LANG[c.meta && c.meta.lang];
  const takeValue = d ? d.user_take || "" : "";
  $("pageRight").innerHTML = `<div class="sheet">
    <div class="desk-head"><h2>${cfg.kind}</h2><span class="rules">${lang ? lang + " · " : ""}${ruleText(cfg)}</span></div>

    <div class="field-label"><span>Your take <i class="tag you">yours</i></span><span class="hint">Stored exactly as you write it. A model never rewrites it.</span></div>
    <textarea class="paper" id="take" placeholder="${c.panel === "op-eds" ? "What does this article miss? What would you add?" : c.panel === "trends" ? "What is your position on this discussion?" : "What can you add that the thread lacks?"}">${esc(takeValue)}</textarea>
    <div class="actions" style="border:0;margin-top:14px;padding-top:0">
      <button class="btn primary" id="draftBtn" type="button"></button>
      <span class="rules block" id="draftHint" title="${S.state.draft_model ? "Drafting model: " + esc(S.state.draft_model) : ""}"></span>
    </div>
    <div id="drafting" class="drafting" hidden><span class="dots"><i></i><i></i><i></i></span><span>Hermes is writing. The take and the source go in; nothing else.</span></div>

    ${d ? editorHtml(d, cfg) : ghostHtml(cfg)}</div>`;
  bindRight();
}

function ghostHtml(cfg) {
  return `<div class="ghost">
    <div class="cap"><b>Your draft will appear here</b>One proposal, written from your profile, the source and your take. You edit it and decide. Nothing is sent anywhere.</div>
    <div class="lines"><i></i><i></i><i></i><i></i><i></i></div>
    <div class="counter" style="margin-top:16px"><span><b>0</b> / ${cfg.cap} ${cfg.unit}</span></div></div>`;
}

function editorHtml(d, cfg) {
  const vers = S.drafts.map((v, i) => `<button type="button" data-ver="${v.id}" aria-pressed="${v.id === S.viewing}" title="${esc(v.model)}">Version ${S.drafts.length - i} · ${v.model === "you (edited)" ? "yours" : "Hermes"}</button>`).join("");
  return `
    <div class="field-label" id="proposedLabel"><span>Proposed ${c_kind()} <i class="tag ai">hermes</i></span><span class="hint">Edit freely. Nothing here has been sent anywhere.</span></div>
    <textarea class="paper" id="draftText">${esc(d.text)}</textarea>
    ${S.cur.panel === "trends" ? `<div class="postcard" id="postcard"></div>` : ""}
    <div class="deskfoot"><div class="counter" id="counter"></div>
    <div class="versions" id="versions">${vers}</div>
    <div class="actions">
      <button class="btn primary" id="copyBtn" type="button">Copy to clipboard</button>
      <button class="btn" id="saveBtn" type="button" hidden>Save my edit</button>
      <span class="spacer"></span>
      <button class="btn ok" id="approveBtn" type="button" ${S.cur.status === "approved" ? "disabled" : ""}>${S.cur.status === "approved" ? "Approved ✓" : "Approve"}</button>
      <button class="btn no" id="dismissBtn" type="button">Dismiss</button>
    </div>
    <div class="gate"><span class="seal"></span><span>Approve only records your decision here. To publish, copy and paste it yourself where you choose.</span></div></div>`;
}
const c_kind = () => ({ "op-eds": "letter", trends: "post", commentary: "reply" }[S.cur.panel]);

function updateCounter() {
  const ta = $("draftText");
  if (!ta) return;
  const cfg = PANELS[S.cur.panel];
  const n = cfg.unit === "chars" ? ta.value.length : countWords(ta.value);
  const over = n > cfg.cap, under = cfg.floor && n < cfg.floor;
  const el = $("counter");
  el.className = "counter" + (over ? " over" : "");
  const cls = over ? "over" : n > cfg.cap * 0.9 ? "warn" : "";
  el.innerHTML = `<span><b>${n}</b> / ${cfg.cap} ${cfg.unit}${over ? ": over the limit" : under ? `: aim for at least ${cfg.floor}` : ""}<span class="meter"><i class="${cls}" style="width:${Math.min(100, Math.round(n / cfg.cap * 100))}%"></i></span></span><span>${S.dirty ? "edited, not saved" : ""}</span>`;
  $("saveBtn") && ($("saveBtn").hidden = !S.dirty);
  const pc = $("postcard");
  if (pc) pc.innerHTML = `<div class="who">You <span>· how it reads</span></div>${esc(ta.value)}`;
}

function grow(ta) { ta.style.height = "auto"; ta.style.height = Math.max(300, ta.scrollHeight + 4) + "px"; }

function bindRight() {
  const d = viewingDraft();
  const take = $("take");
  const saved = localStorage.getItem("take:" + S.cur.id);
  if (!take.value && saved) take.value = saved;       // never lose what you typed
  const label = () => {
    $("draftBtn").textContent = d ? "Draft again with Hermes" : take.value.trim() ? "Draft from my take" : "Let Hermes suggest an angle";
    $("draftHint").textContent = take.value.trim()
      ? "Hermes writes from your position. Usually 15 to 60 seconds."
      : "With no take, Hermes proposes an angle and labels it as its own suggestion, not your belief.";
  };
  take.addEventListener("input", () => { localStorage.setItem("take:" + S.cur.id, take.value); label(); });
  label();
  $("draftBtn").onclick = doDraft;
  if (!d) return;
  const ta = $("draftText");
  grow(ta);
  ta.addEventListener("input", () => { grow(ta); S.dirty = ta.value !== d.text; updateCounter(); });
  updateCounter();
  $("versions").onclick = (e) => {
    const b = e.target.closest("[data-ver]");
    if (!b) return;
    if (S.dirty && !confirm("Discard your unsaved edits to switch version?")) return;
    S.viewing = Number(b.dataset.ver); S.dirty = false; renderLeft(); renderRight();
  };
  $("copyBtn").onclick = doCopy;
  $("saveBtn").onclick = doSaveEdit;
  $("approveBtn").onclick = () => {
    const open = [...document.querySelectorAll("#pageLeft [data-flag]")].filter((b) => !b.checked).length;
    if (open && !confirm(`${open} item(s) in Hermes's checklist are still unchecked. Approve anyway?`)) return;
    setStatus("approved");
  };
  $("dismissBtn").onclick = () => setStatus("dismissed");
}

async function doDraft() {
  if (S.busy) return;
  const take = $("take").value;
  S.busy = true;
  $("draftBtn").disabled = true;
  $("drafting").hidden = false;
  try {
    const r = await api("/api/draft", { id: S.cur.id, take });
    const fresh = await api(`/api/candidate?id=${S.cur.id}`);
    S.cur = fresh;
    S.drafts = fresh.drafts.map((x) => ({ ...x, flags: safeJson(x.flags) }));
    S.viewing = r.draft_id; S.dirty = false;
    setState(fresh.status); renderLeft(); renderRight();
    toast("Draft ready. Read it, edit it, then decide.");
    $("proposedLabel").scrollIntoView({ block: "start", behavior: "smooth" });
    const notes = $("notes"); if (notes) $("pageLeft").scrollTo({ top: notes.offsetTop - 24, behavior: "smooth" });
  } catch (e) {
    $("drafting").hidden = true; $("draftBtn").disabled = false;
    toast("Drafting failed: " + e.message, true);
  } finally { S.busy = false; }
}

async function doCopy() {
  const text = $("draftText").value;
  try { await navigator.clipboard.writeText(text); }
  catch { const t = $("draftText"); t.select(); document.execCommand("copy"); }
  toast("Copied. Paste it where you want it. Nothing was sent.");
}

async function doSaveEdit() {
  try {
    const r = await api("/api/draft/save", { id: S.cur.id, text: $("draftText").value, take: $("take").value });
    const fresh = await api(`/api/candidate?id=${S.cur.id}`);
    S.cur = fresh; S.drafts = fresh.drafts.map((x) => ({ ...x, flags: safeJson(x.flags) }));
    S.viewing = r.draft_id; S.dirty = false; renderLeft(); renderRight();
    toast("Saved as your own version.");
  } catch (e) { toast(e.message, true); }
}

async function setStatus(status) {
  try {
    await api("/api/status", { id: S.cur.id, status });
    S.cur.status = status; S.dirty = false;
    toast(status === "approved" ? "Approved. It stays here until you paste it somewhere." : "Dismissed.");
    if (status === "dismissed") closeSpread(); else { setState(status); renderRight(); }
  } catch (e) { toast(e.message, true); }
}

// ───────── scout, capture, interests ─────────
async function runScout(panel) {
  if (S.scouting) return;
  S.scouting = true;
  const btn = $("scoutBtn");
  btn.disabled = true; btn.textContent = "Scouting…";
  $("progress").hidden = false;
  banner(`Scouting ${panel || "everything"}: fetching sources, then scoring new items with Jev. Usually 30 to 120 seconds.`);
  try {
    const r = await api("/api/scout", { panel: panel || null });
    const s = r.summary;
    const failed = s.failed_sources.length ? ` · <b>${s.failed_sources.length} source(s) failed</b> (${s.failed_sources.join(", ")}; Reddit often rate-limits)` : "";
    banner(`Scout finished in ${s.seconds}s: fetched ${s.fetched} · new ${s.new} · scored ${s.scored} · $${s.cost_usd.toFixed(4)}${failed}`, !!s.failed_sources.length && s.scored === 0);
    await loadState(); await loadItems();
  } catch (e) { banner(esc(e.message), true); }
  finally { S.scouting = false; btn.disabled = false; btn.textContent = "Scout"; $("progress").hidden = true; }
}

// ───────── wiring ─────────
document.addEventListener("click", (e) => {
  const card = e.target.closest(".card");
  if (card) return openSpread(card.dataset.id, card);
  const tab = e.target.closest("[data-tab]");
  if (tab) { $("columns").dataset.active = tab.dataset.tab; renderTabs(); return; }
  const sc = e.target.closest("[data-scout]");
  if (sc) runScout(sc.dataset.scout);
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("spread").hidden && !document.querySelector("dialog[open]")) closeSpread();
  if ((e.key === "Enter" || e.key === " ") && document.activeElement.classList && document.activeElement.classList.contains("card")) {
    e.preventDefault(); openSpread(document.activeElement.dataset.id, document.activeElement);
  }
});
document.addEventListener("change", (e) => {
  if (e.target.matches("[data-lens]")) { S.lens[e.target.dataset.lens] = e.target.value; renderColumns(); }
});

$("backBtn").onclick = closeSpread;
$("scoutBtn").onclick = () => runScout($("scoutScope").value);
$("floor").oninput = (e) => { S.floor = Number(e.target.value); $("floorOut").textContent = S.floor.toFixed(2); };
$("floor").onchange = () => loadItems().catch((e) => toast(e.message, true));
$("captureBtn").onclick = () => $("captureDlg").showModal();
$("captureCancel").onclick = () => $("captureDlg").close();
$("captureForm").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData($("captureForm")), go = $("captureGo");
  go.disabled = true; go.textContent = "Capturing…";
  try {
    await api("/api/capture", { url: f.get("url"), text: f.get("text") || null, panel: f.get("panel") });
    $("captureDlg").close(); $("captureForm").reset();
    toast("Captured and scored."); await loadState(); await loadItems();
  } catch (err) { toast(err.message, true); }
  finally { go.disabled = false; go.textContent = "Capture and score"; }
};
$("interestsBtn").onclick = () => {
  $("interestList").innerHTML = S.state.interests.map((i) => `<li><b>${esc(i.name)}</b><span>${esc(i.description)}</span></li>`).join("");
  $("interestsDlg").showModal();
};
$("interestsClose").onclick = () => $("interestsDlg").close();

(async function init() {
  $("columns").innerHTML = ORDER.map(() => `<section class="col"><div class="col-body"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div></section>`).join("");
  try {
    await loadState();
    S.floor = S.state.min_relevance; $("floor").value = S.floor; $("floorOut").textContent = S.floor.toFixed(2);
    await loadItems();
  } catch (e) { banner(esc(e.message), true); $("columns").innerHTML = ""; }
})();
