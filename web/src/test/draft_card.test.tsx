/** In-app x-brief draft card + Designer PM review items (2026-10-09 evening). Fake API only; never real x-brief. */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fx from "./fixtures.json";
import { DraftCard, xLength } from "../components/DraftCard";
import { HandoffPanel } from "../components/HandoffPanel";
import { ScoutCard } from "../components/ScoutCard";
import { evidenceUrlProblem, defaultHint } from "../copy";
import type { Card, Handoff } from "../api/types";

type Res = { status: number; body: unknown };
let routes: Record<string, (body: unknown) => Res>;
let calls: { method: string; path: string; body: unknown }[];
const ok = (b: unknown): Res => ({ status: 200, body: b });
const MODEL = "SCA pilots show agents can track non-WEIRD behavior where human data exist. https://arxiv.org/abs/2501.06834";
const draftOk = { handoff_id: "h1", status: "ok", draft_text: MODEL, authored_by: "model", label: "model draft",
  gate: { ok: true, reasons: [] }, copy_enabled: true, warnings: [], elapsed_ms: 1200, outlet: "x", door: "EconLLM" };

beforeEach(() => {
  calls = [];
  routes = { "GET /handoff/h1/draft": () => ok({ handoff_id: "h1", draft_text: null }), "POST /handoff/h1/draft": () => ok(draftOk) };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(input, init);
    const path = new URL(req.url, "http://x").pathname.replace(/^\/api/, "");
    const body = req.method === "POST" ? await req.clone().text().then((t) => (t ? JSON.parse(t) : null)) : null;
    calls.push({ method: req.method, path, body });
    const h = routes[`${req.method} ${path}`];
    const r = h ? h(body) : ok({});
    return new Response(JSON.stringify(r.body), { status: r.status, headers: { "content-type": "application/json" } });
  }));
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: vi.fn(async () => {}) } });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const mount = (extra: Partial<Parameters<typeof DraftCard>[0]> = {}) =>
  render(<DraftCard handoffId="h1" outlet="x" what="SCA paper, EconLLM" onFallback={() => {}} debounceMs={0} {...extra} />);

describe("x-brief draft card", () => {
  it("draft:idle — primary 'Write a draft' + the queue note", async () => {
    mount(); await act(async () => {});
    expect(screen.getByTestId("draft-start").textContent).toBe("Write a draft");
    expect(screen.getByTestId("draft-note").textContent).toBe("Drafting can take a minute.");
  });

  it("draft:pending — disabled, 'Writing a draft…', aria-live, no double start", async () => {
    let release!: () => void;
    routes["POST /handoff/h1/draft"] = () => ok(draftOk);
    const gate = new Promise<void>((r) => (release = r));
    const f = globalThis.fetch as ReturnType<typeof vi.fn>;
    const orig = f.getMockImplementation()!;
    f.mockImplementation(async (i: RequestInfo, n?: RequestInit) => { const req = i instanceof Request ? i : new Request(i, n); if (req.method === "POST") await gate; return orig(i, n); });
    mount(); await act(async () => {});
    const b = screen.getByTestId("draft-start") as HTMLButtonElement;
    fireEvent.click(b); fireEvent.click(b); fireEvent.click(b);
    expect(b.disabled).toBe(true);
    expect(b.textContent).toContain("Writing a draft…");
    expect(screen.getByTestId("draft-live").getAttribute("aria-live")).toBe("polite");
    expect(screen.getByTestId("draft-live").textContent).toBe("Writing a draft…");
    await act(async () => { release(); });
    await screen.findByTestId("draft-text");
    expect(calls.filter((c) => c.method === "POST" && c.path === "/handoff/h1/draft").length).toBe(1);
  });

  it("draft:success — 'Model draft' from server, X count with URL = 23, Copy final copies exactly, never a receipt", async () => {
    const onCopied = vi.fn();
    mount({ onCopied }); await act(async () => {});
    await act(async () => { fireEvent.click(screen.getByTestId("draft-start")); });
    expect(screen.getByTestId("draft-author").textContent).toBe("Model draft");
    expect(screen.getByTestId("draft-count").textContent).toBe(`${xLength(MODEL)} / 280`);
    expect(xLength("a https://example.com/very/long/path/that/is/long")).toBe(2 + 23);
    await act(async () => { fireEvent.click(screen.getByTestId("copy-final")); });
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(MODEL);
    expect(screen.getByTestId("copy-final-done").textContent).toBe("Copied for SCA paper, EconLLM");
    expect(calls.some((c) => c.path.includes("receipt") || c.path.includes("wins"))).toBe(false);
    expect(onCopied).toHaveBeenCalledWith(MODEL);
  });

  it("draft:authored_by — label follows the server; UI never sends authored_by", async () => {
    routes["POST /handoff/h1/draft/check"] = (b) => ok({ handoff_id: "h1", gate: { ok: true, reasons: [] }, copy_enabled: true, warnings: [],
      authored_by: ((b as { draft_text: string }).draft_text.trim() === MODEL.trim() ? "model" : "augusto_edit") });
    mount(); await act(async () => {});
    await act(async () => { fireEvent.click(screen.getByTestId("draft-start")); });
    await act(async () => { fireEvent.change(screen.getByTestId("draft-text"), { target: { value: MODEL + "   " } }); });
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/draft/check"))).toBe(true));
    await waitFor(() => expect(screen.getByTestId("draft-author").textContent).toBe("Model draft")); // whitespace-only isn't authorship
    await act(async () => { fireEvent.change(screen.getByTestId("draft-text"), { target: { value: "My own words. " + MODEL } }); });
    await waitFor(() => expect(screen.getByTestId("draft-author").textContent).toBe("Your edit"));
    for (const c of calls) expect(JSON.stringify(c.body ?? {})).not.toMatch(/authored_by/);
    await act(async () => { fireEvent.click(screen.getByTestId("copy-final")); });
    expect(navigator.clipboard.writeText).toHaveBeenLastCalledWith("My own words. " + MODEL);
  });

  it("draft:blocked — each reason verbatim as guidance, Copy final disabled; warnings shown as notes", async () => {
    const reasons = [{ code: "cta_bait", message: "Drop the call to action. Let the claim do the work." },
      { code: "too_long", message: "This is over 280 characters for X." }];
    routes["POST /handoff/h1/draft/check"] = () => ok({ handoff_id: "h1", gate: { ok: false, reasons }, copy_enabled: false, authored_by: "augusto_edit",
      warnings: [{ code: "foreign_handle", message: "The draft mentions @fixture_user_45, who isn't in this handoff." }] });
    mount(); await act(async () => {});
    await act(async () => { fireEvent.click(screen.getByTestId("draft-start")); });
    await act(async () => { fireEvent.change(screen.getByTestId("draft-text"), { target: { value: "DM me @fixture_user_45" } }); });
    await waitFor(() => expect(screen.getByTestId("gate-reasons")).toBeTruthy());
    const items = [...screen.getByTestId("gate-reasons").querySelectorAll("li")].map((l) => l.textContent);
    expect(items).toEqual(reasons.map((r) => r.message));
    expect(screen.getByTestId("gate-reasons").className).toContain("guidance");
    expect(screen.getByTestId("gate-reasons").className).not.toContain("error");
    expect((screen.getByTestId("copy-final") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("draft-warnings").textContent).toContain("@fixture_user_45");
  });

  it("draft:error — x-brief timeout shows plain message and falls back to clipboard handoff", async () => {
    routes["POST /handoff/h1/draft"] = () => ({ status: 502, body: { code: "xbrief_timeout", message: "x-brief took too long and was stopped. Copy the handoff instead." } });
    const onFallback = vi.fn();
    mount({ onFallback }); await act(async () => {});
    await act(async () => { fireEvent.click(screen.getByTestId("draft-start")); });
    expect(screen.getByTestId("draft-error").textContent).toBe("x-brief took too long and was stopped. Copy the handoff instead.");
    expect(onFallback).toHaveBeenCalled();
  });

  it("draft:409 + door_required — plain messages", async () => {
    routes["POST /handoff/h1/draft"] = () => ({ status: 409, body: { code: "already_drafting", message: "Already drafting this one." } });
    mount(); await act(async () => {});
    await act(async () => { fireEvent.click(screen.getByTestId("draft-start")); });
    expect(screen.getByTestId("draft-busy").textContent).toBe("Already drafting this card.");
    cleanup();
    routes["POST /handoff/h1/draft"] = () => ({ status: 422, body: { code: "door_required", message: "door_required" } });
    mount(); await act(async () => {});
    await act(async () => { fireEvent.click(screen.getByTestId("draft-start")); });
    expect(screen.getByTestId("draft-error").textContent).toMatch(/no voice set/);
  });

  it("draft:restore — GET /handoff/{id}/draft restores the saved draft on reload", async () => {
    routes["GET /handoff/h1/draft"] = () => ok({ ...draftOk });
    mount(); await act(async () => {});
    expect((screen.getByTestId("draft-text") as HTMLTextAreaElement).value).toBe(MODEL);
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("panel:fallback — error opens the selectable sealed handoff; no paste-into-x-brief copy", async () => {
    const h = fx.handoff_sca as unknown as Handoff;
    const id = h.payload.handoff_id;
    routes[`POST /handoff/${id}/draft`] = () => ({ status: 502, body: { code: "xbrief_unavailable", message: "x-brief isn't available on this computer right now. Copy the handoff instead." } });
    render(<HandoffPanel handoff={h} assetTitle="SCA paper" />); await act(async () => {});
    expect(document.body.textContent).not.toMatch(/Paste it into x-brief/);
    await act(async () => { fireEvent.click(screen.getByTestId("draft-start")); });
    expect((screen.getByTestId("fallback-text") as HTMLTextAreaElement).value).toContain(id);
    expect((screen.getByTestId("manual-handoff") as HTMLDetailsElement).open).toBe(true);
  });
});

describe("receipt + Designer PM review", () => {
  const h = fx.handoff_sca as unknown as Handoff;
  it("receipt:attest_after_yes + evidence_url + criterion hint", async () => {
    const onReceipt = vi.fn();
    render(<HandoffPanel handoff={h} onReceipt={onReceipt} />); await act(async () => {});
    expect(screen.getByTestId("receipt-answer").tagName).toBe("FIELDSET");
    fireEvent.click(screen.getByTestId("answer-not_yet"));
    expect(screen.queryByTestId("receipt-attest")).toBeNull();
    fireEvent.click(screen.getByTestId("answer-yes"));
    fireEvent.click(screen.getByTestId("receipt-attest"));
    fireEvent.change(screen.getByTestId("receipt-win"), { target: { value: "claim_named_reply" } });
    expect((screen.getByTestId("receipt-criterion") as HTMLSelectElement).value).toBe("original_contribution");
    expect(document.body.textContent).toContain("A hint for your lawyer, not a legal call.");
    expect(document.body.textContent).not.toMatch(/tamper/i);
    const url = screen.getByTestId("receipt-evidence-url");
    fireEvent.change(url, { target: { value: "http://localhost/x" } }); fireEvent.blur(url);
    expect(screen.getByTestId("evidence-url-error").textContent).toMatch(/https:\/\//);
    expect((screen.getByTestId("receipt-submit") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(url, { target: { value: "https://x.com/fixture_user_60/status/9" } });
    await act(async () => { fireEvent.click(screen.getByTestId("receipt-submit")); });
    expect(onReceipt.mock.calls[0][0]).toMatchObject({ evidence_url: "https://x.com/fixture_user_60/status/9", criterion_hint: "original_contribution", win_type: "claim_named_reply" });
  });

  it("receipt:server_error_plain — server refusal shows in plain words", () => {
    render(<HandoffPanel handoff={h} receiptError="A Win needs the public link to the reply, intro or citation." />);
    expect(screen.getByTestId("receipt-error").textContent).toBe("A Win needs the public link to the reply, intro or citation.");
  });

  it("evidence url mirrors server refusals", () => {
    for (const bad of ["", "javascript:alert(1)", "file:///etc/passwd", "https://localhost/a", "https://192.168.1.2/a", "https://10.0.0.1/", "https://172.20.0.1/", "http://x.com/fixture_user_54", "https://intranet/a"])
      expect(evidenceUrlProblem(bad)).not.toBeNull();
    expect(evidenceUrlProblem("https://x.com/fixture_user_54/status/1")).toBeNull();
    expect(defaultHint("warm_intro")).toBe("none");
  });

  it("card:awaiting — primary becomes 'Did you post it?', re-copy is a text link; no_lens inside the card", () => {
    const sca = fx.rec_sca.card as unknown as Card; const civic = fx.rec_civic.card as unknown as Card;
    const onConfirm = vi.fn();
    render(<ScoutCard card={sca} onHandoff={() => {}} onConfirm={onConfirm} pendingUntil="in 3d" />);
    expect(screen.getByTestId("cta-confirm").className).toContain("primary");
    expect(screen.getByTestId("cta-recopy").className).toContain("text-btn");
    expect(screen.queryByTestId("cta-handoff")).toBeNull();
    fireEvent.click(screen.getByTestId("cta-confirm")); expect(onConfirm).toHaveBeenCalled();
    cleanup();
    const nolens = { ...civic, draft: null, handoff_blocked: "no_lens" as const, post_text: "Desinformación en Tucumán" };
    render(<ScoutCard card={nolens} onHandoff={() => {}} onNotForMe={() => {}} onLater={() => {}} />);
    expect(screen.getByTestId("nolens-msg")).toBeTruthy();
    expect(screen.getByTestId("cta-open-post").textContent).toMatch(/Open post/);
  });
});
