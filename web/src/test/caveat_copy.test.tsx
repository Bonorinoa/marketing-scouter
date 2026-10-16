/** Pinned (AT raw_decline1.json): old cvprofiles rows with caveat in stored draft; main copy never carries it. */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import cards from "./raw_decline1_cvprofiles_cards.json";
import { ScoutCard } from "../components/ScoutCard";
import { COPY_WITH_CAVEAT_TOOLTIP, TEMPLATE_NO_DRAFT_LINE, stripCaveat } from "../copy";
import type { Card } from "../api/types";

afterEach(cleanup);
const byId = (id: string) => (cards as unknown as Card[]).find((c) => c.card_id === id)!;
const CAV = "Check the measure before claiming cause and effect.";

describe("caveat never in main copy", () => {
  it("strips the caveat from the old model draft even without API cleanup", () => {
    const c = byId("card_ed8c823e651c");
    render(<ScoutCard card={c} onHandoff={() => {}} />);
    const ta = screen.getByTestId("draft") as HTMLTextAreaElement;
    expect(ta.value).toBe("A measurement that fails every variant is a finding about measurement, not about the phenomenon. The escape hatch is the point.");
    expect(ta.value).not.toContain("Check the measure");
    const sec = screen.getByTestId("cta-copy-with-caveat");
    expect(sec.textContent).toBe("Copy with caveat");
    expect(sec.getAttribute("title")).toBe(COPY_WITH_CAVEAT_TOOLTIP);
    expect(COPY_WITH_CAVEAT_TOOLTIP).toBe("Copies the draft with the caveat as its last line. Whether readers see the caveat is your call.");
  });
  it("template paste flagged by the API: no draft, main copy off", () => {
    const c = { ...byId("card_20747fbd4e57"), no_draft: true, draft: null, copy_enabled: false,
      no_draft_line: TEMPLATE_NO_DRAFT_LINE };
    render(<ScoutCard card={c} onHandoff={() => {}} />);
    expect(screen.getByTestId("no-draft-line").textContent).toBe("No draft: the basic drafter can only repeat your claim, so this one is left blank.");
    expect((screen.getByTestId("cta-handoff") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByTestId("cta-copy-with-caveat")).toBeNull();
  });
  it("caveat-only draft → no draft, copy off", () => {
    const c = { ...byId("card_ed8c823e651c"), draft: CAV.toUpperCase() + "  " };
    render(<ScoutCard card={c} onHandoff={() => {}} />);
    expect(screen.queryByTestId("draft")).toBeNull();
    expect((screen.getByTestId("cta-handoff") as HTMLButtonElement).disabled).toBe(true);
  });
  it("stripCaveat ignores case, spacing, trailing punctuation", () => {
    expect(stripCaveat("Hi there.  check  the measure before claiming cause and effect!", CAV)).toBe("Hi there.");
  });
});
