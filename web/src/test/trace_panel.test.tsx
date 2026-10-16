/** Sprint Wed 4:46: card trace (source → fit grade → score → draft), collapsed, loads on open, read-only GET. */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TracePanel, TraceView, type CardTrace } from "../components/TracePanel";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const T: CardTrace = {
  card_id: "card_x", state: "open",
  source: { url: "https://x.com/fixture_user_54/status/1", status_id: "9000000000000000915", author: "@fixture_user_28", text: "t", card_created_at: "2026-10-14T15:30:47+00:00", age: "9 hours ago" },
  grade: { asset_id: "asset_econllm_lab", asset_title: "EconLLM Lab", slugs: ["econllm-lab"], claim: "c", fit_level: null,
    filter_source: "word", shadow_level: "topic", labels: [],
    cached_grades: [{ asset_id: "asset_econllm_lab", level: "topic", model: "m" }, { asset_id: "asset_cvprofiles", level: "topic", model: "m" }],
    shadow_disagreements: [] },
  score: { S: 83, factors: { Fit: 0.85, Urgency: 1, EffortPenalty: 0 }, note: "" },
  draft: { model: "local_template", status: "ok", code: null, gate: { ok: false, reasons: [{ code: "claim_overlap", message: "m" }] },
    shown: "", no_draft_line: "No draft.", copy_enabled: false, handoff_blocked: null },
  events: [{ ts: "2026-10-14T15:30:47+00:00", kind: "scored", S: 83 }, { ts: "2026-10-14T15:30:47+00:00", kind: "decision", decision: "enqueue" }],
};

describe("TraceView", () => {
  it("shows every step in order with the real values", () => {
    render(<TraceView t={T} />);
    const steps = screen.getByTestId("trace-steps").querySelectorAll("li");
    expect([...steps].map((li) => li.getAttribute("data-testid"))).toEqual(
      ["trace-step-source", "trace-step-grade", "trace-step-score", "trace-step-draft", "trace-step-events"]);
    expect(screen.getByTestId("trace-step-grade").textContent).toContain("games, experiments, LLM agents and complex systems");
    expect(screen.getByTestId("trace-step-grade").textContent).toContain("word match");
    expect(screen.getByTestId("trace-shadow").textContent).toBe("topic");
    expect(screen.getByTestId("trace-step-score").textContent).toContain("83");
    expect(screen.getByTestId("trace-step-draft").textContent).toContain("Built-in drafter · not shown · check: claim_overlap");
    expect(screen.getByTestId("trace-step-events").textContent).toContain("decision: enqueue");
  });
});

describe("TracePanel", () => {
  it("fetches only when opened, with a GET to the card's trace", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(T), { status: 200 }));
    render(<TracePanel cardId="card_x" />);
    expect(f).not.toHaveBeenCalled();
    const d = screen.getByTestId("trace-panel") as HTMLDetailsElement;
    d.open = true; fireEvent(d, new Event("toggle"));
    await waitFor(() => expect(screen.getByTestId("trace-steps")).toBeTruthy());
    expect(f).toHaveBeenCalledTimes(1);
    expect(String(f.mock.calls[0][0])).toMatch(/\/cards\/card_x\/trace$/);
    expect((f.mock.calls[0][1] as RequestInit | undefined)?.method ?? "GET").toBe("GET");
  });
  it("shows a retry on error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 500 }));
    render(<TracePanel cardId="card_x" />);
    const d = screen.getByTestId("trace-panel") as HTMLDetailsElement;
    d.open = true; fireEvent(d, new Event("toggle"));
    await waitFor(() => expect(screen.getByTestId("trace-error").textContent).toContain("Couldn't load the trace."));
  });
});
