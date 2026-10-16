/** Designer P1 #3 (Wed 4:46): X budget 0 left → X primary becomes secondary "Copy reply" with
 *  "X limit reached for today" beneath; no hand-off to X. Budget is replies posted today (API replies_today). */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import fx from "./fixtures.json";
import { ScoutCard } from "../components/ScoutCard";
import { CapMeters, StatusLine, budgetFor } from "../components/Chrome";
import { TOPIC_LABEL } from "../copy";
import type { Card } from "../api/types";

afterEach(cleanup);
const base = ((fx as any).queue?.cards?.[0] ?? (fx as any).cards?.[0]) as Card;
const xCard: Card = { ...base, outlet: "x", draft: "On WVS maps, the GPT answers lean WEIRD in our runs.",
  handoff_blocked: null, no_draft: false, copy_enabled: true, caveat: null, asset: { ...base.asset, caveat: null } };

describe("X budget at zero", () => {
  it("demotes the X primary to a secondary Copy reply with the limit line beneath", () => {
    const onHandoff = vi.fn();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<ScoutCard card={xCard} onHandoff={onHandoff} onNotForMe={() => {}} onLater={() => {}} limitReached />);
    expect(screen.queryByTestId("cta-handoff")).toBeNull();
    const btn = screen.getByTestId("cta-copy-only");
    expect(btn.textContent).toBe("Copy reply");
    expect(btn.className).toContain("secondary");
    expect(btn.className).not.toContain("primary");
    const lim = screen.getByTestId("cta-limit");
    expect(lim.textContent).toBe("X limit reached for today");
    expect(btn.getAttribute("aria-describedby")).toBe(lim.id);
    // beneath: the limit line comes after the button in the action row
    expect(btn.compareDocumentPosition(lim) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(btn);
    expect(writeText).toHaveBeenCalledWith(xCard.draft);
    expect(onHandoff).not.toHaveBeenCalled();        // no hand-off, X is not opened
    expect(screen.getByTestId("cta-copy-only").textContent).toBe("Copied");
  });

  it("keeps the normal primary when budget is left", () => {
    render(<ScoutCard card={xCard} onHandoff={() => {}} />);
    expect(screen.getByTestId("cta-handoff").className).toContain("primary");
    expect(screen.getByTestId("cta-handoff").textContent).toBe("Copy reply & open on X");
    expect(screen.queryByTestId("cta-limit")).toBeNull();
  });

  it("status line reads the daily reply budget, not open queue slots", () => {
    render(<CapMeters cap={{ x: "7/7", linkedin: "0/7" }}
      replies={{ x: { used: 7, max: 7, left: 0 }, linkedin: { used: 1, max: 7, left: 6 } }} />);
    expect(screen.getByTestId("cap-meters").textContent).toBe("X: 0 of 7 left · LinkedIn: 6 of 7");
    cleanup();
    render(<CapMeters cap={{ x: "7/7", linkedin: "0/7" }}
      replies={{ x: { used: 0, max: 7, left: 7 }, linkedin: { used: 0, max: 7, left: 7 } }} />);
    expect(screen.getByTestId("cap-meters").textContent).toBe("X: 7 of 7 left · LinkedIn: 7 of 7");
    expect(budgetFor("x", { x: "3/7" })).toEqual({ left: 4, max: 7 });   // legacy fallback
  });
});

describe("Status line openings count", () => {
  it("counts the cards actually shown, not the store's open cards", () => {
    const st = { x_last_checked: { sentence: "X was last checked just now." }, drafting_ok: true, drafting_reason: "", queue_sentence: "7 cards waiting in the queue." };
    render(<StatusLine status={st} openings={5} />);
    expect(screen.getByTestId("status-line").textContent).toBe("X was last checked just now. · Drafts ready · 5 openings");
    cleanup();
    render(<StatusLine status={st} openings={1} />);
    expect(screen.getByTestId("status-line").textContent).toContain("· 1 opening");
    cleanup();
    render(<StatusLine status={st} />);
    expect(screen.getByTestId("status-line").textContent).toContain("· 7 openings");
  });
});

describe("Marketing topic labels (Wed 4:46)", () => {
  it("uses Marketing's wording exactly", () => {
    expect(TOPIC_LABEL["econllm-lab"]).toBe("games, experiments, LLM agents and complex systems");
    expect(TOPIC_LABEL["gpt4o-weird"]).toBe("GPT-4o-mini leaning toward WEIRD values");
    expect(TOPIC_LABEL["abm-nroy-policy"]).toBe("plausible policy worlds (NROY ranges)");
  });
});
