import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import fx from "./fixtures.json";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { LANG_TOOLTIP } from "../copy";
import { ScoutCard } from "../components/ScoutCard";
import type { Card } from "../api/types";

const base = (fx as any).queue.cards[0] as Card;

describe("Not clearly English chip (lang_capped)", () => {
  afterEach(cleanup);
  it("renders when labels include lang_capped", () => {
    render(<ScoutCard card={{ ...base, labels: ["lang_capped"] }} />);
    const chip = screen.getByTestId("lang-chip");
    expect(chip.firstChild?.textContent).toBe("Not clearly English");
    expect(chip.getAttribute("title")).toBe(LANG_TOOLTIP);
    expect(document.getElementById(chip.getAttribute("aria-describedby")!)?.textContent).toBe(LANG_TOOLTIP);
  });
  it("tooltip and trace copy match docs/TAB-COPY.md", () => {
    const doc = readFileSync(resolve(__dirname, "../../../docs/TAB-COPY.md"), "utf8");
    expect(doc).toContain(`- Tooltip: "${LANG_TOOLTIP}"`);
    expect(doc).toContain('- Trace line: "Language: {lang} · capped at topic ({reason})"');
  });
  it("trace line: non_latin_script stays, other gate reasons read lang_capped", () => {
    render(<ScoutCard card={{ ...base, labels: ["lang_capped"],
      fit_trace: { lang: { lang: "non_latin", reason: "non_latin_script" } } }} />);
    expect(screen.getByTestId("lang-trace").textContent).toBe("Language: non_latin · capped at topic (non_latin_script)");
    cleanup();
    render(<ScoutCard card={{ ...base, labels: ["lang_capped"],
      fit_trace: { lang: { lang: "es", reason: "non_english_words" } } }} />);
    expect(screen.getByTestId("lang-trace").textContent).toBe("Language: es · capped at topic (lang_capped)");
  });
  it("no trace line without the label or trace", () => {
    render(<ScoutCard card={{ ...base, labels: ["lang_capped"], fit_trace: null }} />);
    expect(screen.queryByTestId("lang-trace")).toBeNull();
  });
  it("is absent without the label", () => {
    render(<ScoutCard card={{ ...base, labels: [] }} />);
    expect(screen.queryByTestId("lang-chip")).toBeNull();
  });
});
