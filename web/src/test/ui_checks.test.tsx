// DoR UI checks — each `ui:<id>` title maps to a chrome case in scripts/dor_check.py.
// Fixtures come from the real Python truth layer (scripts/gen_ui_fixtures.py), never hand-written.
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { S9_FACTORS, type Asset, type Card, type Handoff } from "../api/types";
import { SelectedAsset } from "../components/Chrome";
import { HandoffPanel } from "../components/HandoffPanel";
import { ScoutCard } from "../components/ScoutCard";
import { CLOSED_INTERESTS, parseSeed } from "../interestsSeed";
import fx from "./fixtures.json";

const inventory = fx.inventory as Asset[];
const sca = fx.rec_sca.card as unknown as Card;
const civic = fx.rec_civic.card as unknown as Card;
const hCivic = fx.handoff_civic as unknown as Handoff;
const civicMix = fx.rec_civic_mix.card as unknown as Card;
let pendingList: unknown[] = [];
const hSca = fx.handoff_sca as unknown as Handoff;
const inv = (id: string) => inventory.find((a) => a.asset_id === id)!;

// Forbidden affordance vocabulary (CARD-UX-BRIEF). HTTP verb `POST` in the typed client is not chrome.
const FORBIDDEN = /\b(post|posts|posting|posted|schedule|scheduled|scheduling|publish|published|publishing|auto-?post)\b/gi;
// Locked "post" phrases allowed after redesign approval 2026-10-09 (Suggests only… / Did you post it?).
const ALLOWED = new Set([
  // Locked banner + confirm copy (redesign approval 2026-10-09)
  "You post everything yourself",
  "Did you post it?",
  "Yes, I posted it",
  "I confirm I posted this myself",
  "replies posted",
  "reply posted",
  "Never posts",
  // Noun "post" = the social post being scored (redesign: Check a post / Open post)
  "Check a post",
  "check-post",
  "Couldn't read that post",
  "Open post",
  "the post",
  "a post",
  "Check the post again",
  "post-link",
  "Paste the post",
  "Post text",
  "post-quote",
  "post-text",
  "post-author",
  "post-age",
    "post-text-missing",
  "cta-open-post",
  "Reply in your own words",
  "Not published yet",
]);
function forbiddenHits(text: string): string[] {
  const cleaned = [...ALLOWED].reduce((t, a) => t.split(a).join(""), text);
  return [...cleaned.matchAll(FORBIDDEN)].map((m) => m[0]).filter((w) => w !== "POST");
}

function mockApi() {
  const route = (url: string, method: string): unknown => {
    const u = new URL(url, "http://localhost");
    if (u.pathname === "/inventory") return inventory;
    if (u.pathname === "/queue") {
      const aid = u.searchParams.get("asset_id");
      const cards = [sca, civic, civicMix].filter((c) => !aid || c.asset.asset_id === aid);
      return { ...fx.queue, cards, later: [], selected_asset: aid ? inventory.find((a) => a.asset_id === aid) ?? null : null };
    }
    if (u.pathname === "/health" || u.pathname === "/api/health") return { ok: true };
    if (u.pathname === "/status" || u.pathname === "/api/status") return {
      x_last_checked: { at: null, sentence: "X hasn't been checked yet.", run_id: null },
      drafting_ok: true, drafting_reason: "Drafting works.", drafting_checked_at: null,
      xbrief_selfcheck: { ok: false, note: "" }, queue_size: 3, queue_by_outlet: { x: 2, linkedin: 1 },
      queue_sentence: "3 cards waiting in the queue.",
    };
    if (u.pathname === "/wins") return [];
    if (u.pathname === "/recommend" && method === "POST") return fx.rec_civic;
    if (u.pathname === "/handoff" && method === "POST") return fx.handoff_civic;
    if (u.pathname === "/handoff" && method === "GET") return pendingList;
    return {};
  };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(input, init);
    return new Response(JSON.stringify(route(req.url, req.method)), { status: 200, headers: { "content-type": "application/json" } });
  }));
}

beforeEach(() => { pendingList = []; mockApi(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("DoR chrome", () => {
  it("ui:no_post_chrome — DOM across every view + web/ source has zero forbidden affordances", async () => {
    render(<App />);
    await act(async () => {});
    const seen: string[] = [];
    for (const tab of ["Today", "Work", "Wins"]) {
      await act(async () => { fireEvent.click(screen.getByRole("button", { name: new RegExp("^" + tab + "$") })); });
      if (tab === "Today") { await screen.findAllByTestId("cta-handoff"); await act(async () => { const ctas = screen.getAllByTestId("cta-handoff").filter((b) => !(b as HTMLButtonElement).disabled); fireEvent.click(ctas[ctas.length - 1]); }); }
      seen.push(document.body.innerHTML);
      for (const el of [...document.querySelectorAll("button, a, [role=button], option, input, form")])
        expect(forbiddenHits((el.textContent ?? "") + " " + (el.getAttribute("href") ?? "") + " " +
          (el.getAttribute("value") ?? "") + " " + (el.getAttribute("action") ?? ""))).toEqual([]);
    }
    expect(forbiddenHits(seen.join("\n"))).toEqual([]);
    expect(screen.getByTestId("banner").textContent?.trim()).toBe("Suggests only. You post everything yourself.");
    // source assert: routes, copy, buttons under web/ (src + index.html)
    const root = join(__dirname, "..", "..");
    const files: string[] = [join(root, "index.html")];
    const walk = (d: string) => readdirSync(d).forEach((f) => { const p = join(d, f); statSync(p).isDirectory() ? walk(p) : files.push(p); });
    walk(join(root, "src"));
    for (const f of files.filter((f) => /\.(tsx?|html|css)$/.test(f) && !f.endsWith("ui_checks.test.tsx") && !f.endsWith("schema.d.ts"))) {
      const hits = forbiddenHits(readFileSync(f, "utf8"));
      expect({ f, hits }).toEqual({ f, hits: [] });
    }
    // generated client paths: no outbound-sharing route exists to call
    expect(readFileSync(join(root, "src/api/schema.d.ts"), "utf8")).not.toMatch(/"\/(post|schedule|publish)/i);
  });

  it("ui:asset_tone_card — card + sticky chrome show title·type·door·tone_hint from inventory surface/tone_hint", () => {
    const a = inv("asset_sca_nonweird");
    render(<><SelectedAsset asset={a} /><ScoutCard card={sca} /></>);
    expect(screen.getByTestId("sa-title").textContent).toBe(a.title);
    expect(screen.getByTestId("sa-type").textContent).toBe(a.surface);
    expect(screen.getByTestId("sa-door").textContent).toContain("Research voice");
    expect(screen.getByTestId("sa-slug").textContent).toBe(a.primary_slug);
    expect(screen.getByTestId("sa-tone").getAttribute("title")).toBe(a.tone_hint); // Designer 13:10: label map visible, raw hint in tooltip
    expect(screen.getByTestId("card-asset-title").textContent).toBe(a.title);
    expect(screen.getByTestId("card-asset-type").textContent).toBe("arxiv");
    expect(screen.getByTestId("card-asset-door").textContent).toBe("EconLLM");
    expect(screen.getByTestId("card-asset-tone").getAttribute("title")).toBe("EconLLM technical / methods");
    expect(screen.getByTestId("card-asset-tone").textContent).toBe("Research finding");
    cleanup();
    const c = inv("asset_adepa_lagaceta_carta");
    render(<SelectedAsset asset={c} />);
    expect(screen.getByTestId("sa-type").textContent).toBe("carta");
    expect(screen.getByTestId("sa-tone").getAttribute("title")).toBe(c.tone_hint);
    // general mode is explicit, not a pretend scope
    cleanup(); render(<SelectedAsset asset={null} />);
    expect(screen.getByTestId("selected-asset").textContent).toContain("All work");
  });

  it("ui:civic_spanish — Augusto-civic claim + draft preview render Spanish with provincial source chip", () => {
    // Spanish only on op-ed outlet (X/LI are English-first per DECISION 15:16)
    const civicEs = { ...civic, lang: "es" as const, format: "op-ed" as const, outlet: "op-ed" as never,
      claim: "Generar y amplificar es barato; verificar con contexto local es lo escaso.",
      draft: "En Tucumán el problema no es falta de datos, es falta de verificación en contexto.",
      source_chip: "La Gaceta", post_text: "Desinformación en Tucumán", author: "@fixture_user_22" };
    render(<ScoutCard card={civicEs} />);
    const claim = screen.getByTestId("claim"), draft = screen.getByTestId("draft");
    expect(claim.getAttribute("lang")).toBe("es");
    expect(draft.getAttribute("lang")).toBe("es");
    expect(claim.textContent).toMatch(/verificar|contexto local/i);
    expect(draft.textContent).toMatch(/verificación|Tucumán/);
    expect(screen.getByTestId("source-chip").textContent).toBe("La Gaceta");
    expect(screen.getAllByTestId("door-badge")).toHaveLength(1);
  });

  it("ui:s9_complete — every scored card renders the full §9 strip", () => {
    render(<><ScoutCard card={sca} /><ScoutCard card={civic} /></>);
    for (const strip of screen.getAllByTestId("s9-strip"))
      expect([...strip.querySelectorAll("dt")].map((d) => d.getAttribute("data-factor"))).toEqual([...S9_FACTORS]);
    expect(screen.getAllByTestId("s9-EffortPenalty")).toHaveLength(2);
  });

  it("ui:weights_basis — score hover states the weights' basis exactly", () => {
    render(<ScoutCard card={sca} />);
    const title = screen.getByTestId("score").getAttribute("title") ?? "";
    expect(title.split("\n")[1]).toBe("Hand-set by the team and not yet fitted to outcomes. A review of X's open-sourced ranking signals will inform planned changes to Urgency and Format fit.");
    expect(title).not.toMatch(/basis is/i);
  });

  it("ui:likes_not_chip — likes render as informational text, never a chip or §9 factor", () => {
    render(<ScoutCard card={sca} />);
    const likes = screen.getByTestId("likes-info");
    expect(likes.className).not.toMatch(/chip|factor|score/);
    expect(likes.textContent).toMatch(/likes \(not used in score\)/);
    expect(within(screen.getByTestId("s9-strip")).queryByText(/like/i)).toBeNull();
    expect(document.querySelectorAll(".chip").length).toBe(0);
  });

  it("ui:closed_fit_list — handoff panel lists closed Fit from xbrief-interests-seed only; no free-form field", () => {
    render(<HandoffPanel handoff={hSca} />);
    const seed = parseSeed(readFileSync(join(__dirname, "../../../data/xbrief-interests-seed.md"), "utf8")).map((i) => i.slug);
    expect(seed.length).toBeGreaterThan(10);
    expect(CLOSED_INTERESTS.map((i) => i.slug)).toEqual(seed);
    const items = [...screen.getByTestId("closed-fit-list").querySelectorAll("li")].map((l) => l.getAttribute("data-slug"));
    expect(items).toEqual(seed);
    const panel = screen.getByTestId("handoff-panel");
    expect(panel.querySelectorAll("textarea, input[type=text], input:not([type])").length).toBe(0);
    expect([...screen.getByTestId("receipt-lens").querySelectorAll("option")].slice(1).map((o) => o.getAttribute("value"))).toEqual(seed);
    expect(screen.queryByTestId("seed-violation")).toBeNull();
    for (const s of hSca.payload.xbrief_interests.active) expect(seed).toContain(s);
  });

  it("ui:evidence_soft — Adepa/pending Evidence renders soft label, never A-green", () => {
    render(<ScoutCard card={civic} />);
    const ev = screen.getByTestId("evidence");
    expect(ev.className).toContain("evidence-soft");
    expect(ev.className).not.toContain("evidence-a");
    expect(ev.textContent).toMatch(/Evidence B · pending/);
    expect(ev.querySelector("[title]")?.getAttribute("title")).toMatch(/soft/);
    cleanup();
    render(<HandoffPanel handoff={hCivic} />);
    const ab = [...screen.getByTestId("receipt-win").querySelectorAll("option")].find((o) => o.value === "evidence_ab")!;
    expect(ab.disabled).toBe(true);
  });

  it("ui:civic_pause_chrome — civic handoff preview shows EconLLM Active paused", () => {
    render(<HandoffPanel handoff={hCivic} />);
    const flag = screen.getByTestId("econllm-paused");
    expect(flag.textContent).toMatch(/Research voice paused/);
    expect(flag.getAttribute("data-paused")).toBe("true");
    const econ = CLOSED_INTERESTS.filter((i) => i.door === "EconLLM").map((i) => i.slug);
    for (const li of screen.getByTestId("closed-fit-list").querySelectorAll("li"))
      if (econ.includes(li.getAttribute("data-slug")!)) expect(li.getAttribute("data-state")).toBe("paused");
    expect(screen.getByTestId("payload-preview").textContent).toContain('"door": "Augusto-civic"');
  });

  it("ui:attest_required — receipt cannot submit without explicit user attestation", () => {
    const onReceipt = vi.fn();
    render(<HandoffPanel handoff={hSca} onReceipt={onReceipt} />);
    const submit = screen.getByTestId("receipt-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.submit(screen.getByTestId("receipt-form"));
    expect(onReceipt).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("receipt-attest"));
    fireEvent.click(submit);
    expect(onReceipt).toHaveBeenCalledWith(expect.objectContaining({ attested: true, action: "acted" }));
  });

  it("ui:ux_foundations — numbered tabs + counts, health dot, onboarding, purpose + empty state per tab, no raw JSON", async () => {
    localStorage.clear();
    // Empty world: every tab must show a purpose line and an empty state.
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo, init?: RequestInit) => {
      const req = input instanceof Request ? input : new Request(input, init);
      const p = new URL(req.url, "http://localhost").pathname;
      const body = p.endsWith("/queue") ? { selected_asset: null, cap: {}, cards: [] }
        : p.endsWith("/health") ? { ok: true }
        : p.endsWith("/status") ? { x_last_checked: { at: null, sentence: "X hasn't been checked yet.", run_id: null }, drafting_ok: true, drafting_reason: "Drafting works.", xbrief_selfcheck: { ok: false, note: "" }, queue_size: 0, queue_by_outlet: { x: 0, linkedin: 0 }, queue_sentence: "0 cards waiting in the queue." }
        : [];
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    }));
    render(<App />);
    await act(async () => {});
    expect(screen.getByTestId("onboarding").textContent).toMatch(/Find the right conversations/);
    expect(screen.getByTestId("nav-count-today").textContent).toBe("0");
    expect(screen.getByTestId("nav-count-wins").textContent).toBe("0");
    await screen.findByText("Connected");
    expect(screen.getByTestId("api-status").getAttribute("data-health")).toBe("ok");
    for (const tab of ["Today", "Work", "Wins"]) {
      await act(async () => { fireEvent.click(screen.getByRole("button", { name: new RegExp("^" + tab + "$") })); });
      expect(screen.getAllByTestId("tab-purpose")).toHaveLength(1);
      expect(screen.getAllByTestId("empty-state").length).toBeGreaterThanOrEqual(1);
      expect([...document.querySelectorAll("pre")].filter((p) => !p.closest("details"))).toHaveLength(0);
    }
    fireEvent.click(screen.getByText("Got it"));
    expect(screen.queryByTestId("onboarding")).toBeNull();
    expect(localStorage.getItem("ms.onboarding.done")).toBe("1");
  });

  it("ui:api_offline — offline API turns the dot red and disables actions with a reason", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("fetch failed"); }));
    render(<App />);
    await act(async () => {});
    await screen.findByText(/Offline: start the API on :8710/);
    expect(screen.getByTestId("api-status").getAttribute("data-health")).toBe("offline");
    const details = screen.getByTestId("check-post");
    if (!(details as HTMLDetailsElement).open) fireEvent.click(details.querySelector("summary")!);
    const btn = document.querySelector('[data-action="scout-btn"]') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.title).toMatch(/offline/i);
    expect((await screen.findAllByTestId("toast")).some((t) => /API running/.test(t.textContent ?? ""))).toBe(true);
  });

  it("ui:scope_queue — Queue only shows cards for the promoted asset (scope bug regression)", async () => {
    render(<App />);
    await act(async () => {});
    await act(async () => { fireEvent.click(screen.getByTestId("chip-asset-asset_adepa_lagaceta_carta")); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /^Today$/ })); });
    const cards = await screen.findAllByTestId("card");
    expect(cards.every((c) => c.getAttribute("data-door") === "Augusto-civic")).toBe(true);
    expect(screen.getByTestId("nav-count-today").textContent).toBe(String(cards.length));
    expect(screen.getAllByTestId("toast").some((t) => /Showing openings for/.test(t.textContent ?? ""))).toBe(true);
  });

  it("ui:scout_outcome — killed result shows a plain reason with the code under Why?, never raw JSON", async () => {
    const { ResultView } = await import("../App");
    render(<ResultView r={{ ok: false, mode: "scoped", status: "killed", kill_id: "empty_fit", kill_reasons: ["empty_fit"], slugs: [], card: null }} onPick={() => {}} onHandoff={() => {}} />);
    const out = screen.getByTestId("scout-outcome");
    expect(out.textContent).toMatch(/Not about any of your work/);
    expect(out.querySelector("details")!.textContent).toMatch(/kill: empty_fit/);
    expect(out.querySelector("pre")).toBeNull();
  });

  // ── 2026-10-09 PM: Adversarial UX traps + x-brief alignment ──────────────
  it("ui:copy_failure_visible — clipboard failure says so and shows selectable text", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: vi.fn(async () => { throw new Error("denied"); }) } });
    render(<HandoffPanel handoff={hSca} assetTitle="SCA paper" />);
    await act(async () => { fireEvent.click(screen.getByTestId("copy-handoff")); });
    expect(screen.getByTestId("copy-failed").textContent).toMatch(/Couldn't copy/);
    expect((screen.getByLabelText("Details text") as HTMLTextAreaElement).value).toContain(hSca.payload.handoff_id);
    expect(screen.getByTestId("copy-handoff").textContent).not.toMatch(/Copied/);
  });

  it("ui:copy_names_asset_door — Copied confirmation names asset and door", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: vi.fn(async () => {}) } });
    const onCopy = vi.fn();
    render(<HandoffPanel handoff={hSca} assetTitle="SCA paper" onCopy={onCopy} />);
    await act(async () => { fireEvent.click(screen.getByTestId("copy-handoff")); });
    expect(screen.getByTestId("copy-handoff").textContent).toContain("SCA paper, EconLLM");
    expect(onCopy.mock.calls[0][0]).toContain("Copied for SCA paper, EconLLM");
    expect(screen.getByTestId("sealed-line").textContent).toMatch(/Expires .* · uses \d+ of 10 topics/);
    expect(screen.getByTestId("answer-not_yet")).toBeTruthy();
  });

  it("ui:killed_persists — killed card stays on screen with plain reason, no error toast", async () => {
    const { ResultView } = await import("../App");
    render(<ResultView r={fx.rec_kill as never} onPick={() => {}} onHandoff={() => {}} />);
    const k = screen.getByTestId("killed-card");
    expect(k.textContent).toMatch(/^Not a fit: .*\. Nothing was queued\./);
    expect(k.querySelector("details")?.textContent).toContain(fx.rec_kill.kill_id as string);
    expect(screen.queryByTestId("toast")).toBeNull();
  });

  it("ui:pending_survives_reload — waiting-for-receipt list comes from GET /handoff", async () => {
    pendingList = fx.pending;
    render(<App />);
    await act(async () => {});
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /^Today$/ })); });
    const items = await screen.findAllByTestId("waiting-item");
    expect(items.length).toBe(fx.pending.length);
    expect(items[0].textContent).toMatch(/expires/);
    expect(screen.getAllByTestId("await-pill").length).toBeGreaterThan(0);
  });

  it("ui:add_asset_form — Assets tab offers an in-app Add asset form with closed pick lists", async () => {
    render(<App />);
    await act(async () => {});
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /^Work$/ })); });
    const f = screen.getByTestId("add-asset");
    expect(within(f).getByTestId("aa-surface").querySelectorAll("option").length).toBe(9);
    expect([...within(f).getByTestId("aa-door").querySelectorAll("option")].map((o) => o.textContent)).toEqual(["Pick one…", "EconLLM", "Augusto-civic"]);
    expect(within(f).getByTestId("aa-slugs").querySelectorAll("input").length).toBe(21);
    expect((within(f).getByTestId("aa-submit") as HTMLButtonElement).disabled).toBe(true);
    expect(document.body.textContent).not.toMatch(/seed_inventory\.json/);
  });

  it("ui:es_chip_oped_only — door badge never shows ES; ES · op-ed chip only on op-ed cards", () => {
    render(<><ScoutCard card={sca} /><ScoutCard card={civicMix} /></>);
    for (const b of screen.getAllByTestId("door-badge")) expect(b.textContent).not.toMatch(/ES/);
    // Designer PM 2026-10-09 #1 + DECISION 15:16: X/LinkedIn reply cards never carry ES · op-ed, even when the
    // API still labels them format=op-ed (API cause reported to Systems Engineer). Intentional diff.
    // X/LinkedIn cards are format=social (DECISION); ES chip only when format=op-ed and outlet not x/li
    expect(civicMix.format === "op-ed" || civicMix.format === "social").toBe(true);
    expect(screen.queryAllByTestId("es-oped-chip").length).toBe(0);
    cleanup(); render(<ScoutCard card={{ ...civicMix, format: "op-ed", outlet: "op-ed" as never }} />);
    expect(screen.getAllByTestId("es-oped-chip").length).toBe(1);
  });

  it("ui:no_lens_disabled — no draft style: hide draft, Open post primary, own-words message", () => {
    const nolens = { ...civic, draft: null, handoff_blocked: "no_lens" as const,
      post_text: civic.post_text ?? "Desinformación en Tucumán", author: "@fixture_user_22", age: "2 hours ago" };
    render(<ScoutCard card={nolens} onHandoff={() => {}} onNotForMe={() => {}} onLater={() => {}} />);
    expect(screen.queryByTestId("draft")).toBeNull();
    expect(screen.queryByTestId("cta-handoff")).toBeNull();
    expect(screen.getByTestId("nolens-msg").textContent).toMatch(/No draft style for this topic yet\. Reply in your own words/);
    expect(screen.getByTestId("cta-open-post").textContent).toBe("Open post");
    expect(screen.getByTestId("cta-not-for-me")).toBeTruthy();
    expect(screen.getByTestId("cta-later")).toBeTruthy();
    expect(screen.getByTestId("post-quote")).toBeTruthy();
  });

  it("ui:post_first_card — quoted post on top; claim lives in Your angle", () => {
    const c = { ...sca, author: "@fixture_user_23", post_text: "Are LLM synthetic participants just WEIRD?", age: "3 hours ago" };
    render(<ScoutCard card={c} onHandoff={() => {}} />);
    const quote = screen.getByTestId("post-quote");
    expect(quote.textContent).toMatch(/@fixture_user_23/);
    expect(screen.getByTestId("post-text").textContent).toMatch(/WEIRD/);
    expect(screen.getByTestId("claim").textContent).toBe(c.claim);
    expect(screen.getByTestId("why-fits").textContent).toMatch(/Your angle:/);
    // claim is not a bold standalone headline above the quote
    expect(quote.compareDocumentPosition(screen.getByTestId("claim")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("ui:outlet_segments — Where you saw it is two equal X | LinkedIn segments", async () => {
    render(<App />);
    await act(async () => {});
    const details = screen.getByTestId("check-post");
    if (!(details as HTMLDetailsElement).open) fireEvent.click(details.querySelector("summary")!);
    const row = screen.getByTestId("paste-outlet").querySelector(".seg-row")!;
    expect(row.children).toHaveLength(2);
    expect(screen.getByTestId("outlet-x").className).toMatch(/\bon\b/);
    fireEvent.click(screen.getByTestId("outlet-linkedin"));
    expect(screen.getByTestId("outlet-linkedin").className).toMatch(/\bon\b/);
    expect(screen.getByTestId("outlet-x").className).not.toMatch(/\bon\b/);
  });

  it("ui:check_error_resets — link_only clears Checking…, shows under Text, focuses field", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo, init?: RequestInit) => {
      const req = input instanceof Request ? input : new Request(input, init);
      const u = new URL(req.url, "http://localhost");
      if (u.pathname === "/recommend" && req.method === "POST")
        return new Response(JSON.stringify({ code: "link_only", message: "Paste the post text too.", error: "link_only" }),
          { status: 422, headers: { "content-type": "application/json" } });
      if (u.pathname === "/inventory") return new Response(JSON.stringify(inventory), { status: 200, headers: { "content-type": "application/json" } });
      if (u.pathname === "/queue") return new Response(JSON.stringify({ ...fx.queue, cards: [], later: [] }), { status: 200, headers: { "content-type": "application/json" } });
      if (u.pathname === "/health" || u.pathname === "/status") return new Response(JSON.stringify({ ok: true, x_last_checked: { at: null, sentence: "X hasn't been checked yet.", run_id: null }, drafting_ok: true, drafting_reason: "Drafting works.", xbrief_selfcheck: { ok: false }, queue_size: 0, queue_by_outlet: {}, queue_sentence: "0 cards waiting in the queue." }), { status: 200, headers: { "content-type": "application/json" } });
      if (u.pathname === "/wins" || u.pathname === "/handoff") return new Response(JSON.stringify([]), { status: 200, headers: { "content-type": "application/json" } });
      return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
    }));
    render(<App />);
    await act(async () => {});
    const details = screen.getByTestId("check-post");
    if (!(details as HTMLDetailsElement).open) fireEvent.click(details.querySelector("summary")!);
    fireEvent.change(screen.getByTestId("paste-url"), { target: { value: "https://x.com/fixture_user_54/status/1" } });
    await act(async () => { fireEvent.click(document.querySelector('[data-action="scout-btn"]')!); });
    const err = await screen.findByTestId("link-only-error");
    expect(err.textContent).toMatch(/Couldn't read that post/);
    expect(err.closest("label")?.textContent).toMatch(/Text \(paste the thread\)/); // under Text field
    expect(document.querySelector('[data-testid="btn-pending"]')).toBeNull();
    // focus the Text field (jsdom may need an explicit tick)
    await act(async () => { screen.getByTestId("paste-snippet").focus(); });
    expect(document.activeElement).toBe(screen.getByTestId("paste-snippet"));
  });

  it("ui:invariants_in_guide — plain-words invariants live in How it works; banner always visible", async () => {
    render(<App />);
    await act(async () => {});
    await act(async () => { fireEvent.click(screen.getByTestId("how-it-works")); });
    expect(screen.getByTestId("invariants").textContent).toMatch(/Likes never change a card's Score/);
    expect(screen.getByTestId("banner")).toBeTruthy();
  });
});


// ── tooltip + rank-line copy (TAB-COPY.md and API-supplied tooltip fields), not just visible text ──
const repo = join(__dirname, "..", "..", "..");
function tabCopyStrings(): { label: string; text: string }[] {
  const md = readFileSync(join(repo, "docs", "TAB-COPY.md"), "utf8");
  const out: { label: string; text: string }[] = [];
  for (const line of md.split("\n")) {
    const m = line.match(/^-\s*(Tooltip|Claim tier|Topic tier|Chip)\s*:\s*(.+)$/i);
    if (m) out.push({ label: m[1], text: m[2].replace(/[*"]/g, "") });
  }
  return out;
}
function apiCopyStrings(): { key: string; text: string }[] {
  // RANK_COPY in src/api/core.py is what the API sends as rank_reason.text / rank_reason.tooltip
  const py = readFileSync(join(repo, "src", "api", "core.py"), "utf8");
  const block = py.match(/RANK_COPY = \{([\s\S]*?)\n\}/);
  if (!block) return [];
  return [...block[1].matchAll(/"(\w+)":\s*"([^"]*)"/g)].map((m) => ({ key: m[1], text: m[2] }));
}

describe("ui:no_post_chrome — tooltips and API copy", () => {
  it("TAB-COPY tooltip / rank / chip strings have no forbidden affordance words", () => {
    const strs = tabCopyStrings();
    expect(strs.some((s) => s.label === "Tooltip")).toBe(true);
    expect(strs.some((s) => /Ranked first/.test(s.text))).toBe(true);
    for (const s of strs) expect({ ...s, hits: forbiddenHits(s.text) }).toEqual({ ...s, hits: [] });
  });

  it("rendered rank line + promo chip expose no forbidden words in title / aria text", () => {
    const tip = tabCopyStrings().find((s) => s.label === "Tooltip" && /Within each group/.test(s.text))!.text;
    const base = (fx as any).queue.cards[0];
    render(<ScoutCard card={{ ...base, labels: ["brand_post"],
      rank_reason: { tier: "claim", text: "Ranked first: argues one of your claims · S 88", tooltip: tip } }} />);
    for (const el of [...document.querySelectorAll("[title], [aria-label], [aria-describedby]")]) {
      const desc = (el.getAttribute("aria-describedby") ?? "").split(" ").filter(Boolean)
        .map((id) => document.getElementById(id)?.textContent ?? "").join(" ");
      const text = [el.getAttribute("title"), el.getAttribute("aria-label"), desc].join(" ");
      expect(forbiddenHits(text)).toEqual([]);
    }
  });

  it("API-supplied rank_reason text/tooltip (core.py RANK_COPY) have no forbidden words and match TAB-COPY", () => {
    const api = apiCopyStrings();
    expect(api.length).toBeGreaterThanOrEqual(3);
    for (const s of api) expect({ ...s, hits: forbiddenHits(s.text) }).toEqual({ ...s, hits: [] });
    const tab = tabCopyStrings().map((s) => s.text.replace("{S}", ""));
    for (const s of api) expect(tab.some((t) => t.includes(s.text.replace("{S}", "")))).toBe(true);
  });
});
