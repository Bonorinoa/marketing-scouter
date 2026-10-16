import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import fx from "./fixtures.json";
import { ScoutCard } from "../components/ScoutCard";
import type { Card } from "../api/types";

const base = (fx as any).queue.cards[0] as Card;
const rr = (tier: "claim" | "topic", text: string) => ({ tier, text, tooltip: "Within each group, higher S ranks higher." });

describe("claim-first rank line", () => {
  afterEach(cleanup);
  it("shows the claim tier line from the API", () => {
    render(<ScoutCard card={{ ...base, rank_reason: rr("claim", "Ranked first: argues one of your claims · S 88") }} />);
    const el = screen.getByTestId("rank-line");
    expect(el.textContent).toBe("Ranked first: argues one of your claims · S 88");
    expect(el.className).toContain("tier-claim");
    expect(el.tabIndex).toBe(0);
    expect(el.getAttribute("title")).toContain("higher S ranks higher");
  });
  it("shows the topic tier line", () => {
    render(<ScoutCard card={{ ...base, rank_reason: rr("topic", "On your topic, no claim to answer · S 80") }} />);
    expect(screen.getByTestId("rank-line").textContent).toBe("On your topic, no claim to answer · S 80");
  });
  it("is hidden when the flag is off (rank_reason null)", () => {
    render(<ScoutCard card={{ ...base, rank_reason: null }} />);
    expect(screen.queryByTestId("rank-line")).toBeNull();
  });
});
