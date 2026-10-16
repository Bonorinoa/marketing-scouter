import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import fx from "./fixtures.json";
import { ScoutCard } from "../components/ScoutCard";
import type { Card } from "../api/types";

const base = (fx as any).queue.cards[0] as Card;
const TIP = "From a company account, or carries a product link or sign-up pitch. No draft prepared; reply only if it's worth it to you.";

describe("Promotional chip (brand_post)", () => {
  afterEach(cleanup);
  it("renders accessibly when labels include brand_post", () => {
    render(<ScoutCard card={{ ...base, labels: ["brand_post"] }} />);
    const chip = screen.getByTestId("brand-chip");
    expect(chip.textContent).toContain("Promotional");
    expect(chip.getAttribute("title")).toBe(TIP);
    expect(chip.tabIndex).toBe(0);
    const tip = document.getElementById(chip.getAttribute("aria-describedby")!);
    expect(tip?.textContent).toBe(TIP);
  });
  it("is absent without the label", () => {
    render(<ScoutCard card={{ ...base, labels: [] }} />);
    expect(screen.queryByTestId("brand-chip")).toBeNull();
  });
});
