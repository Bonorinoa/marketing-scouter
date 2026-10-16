/** Researcher: claim + caveat render byte-for-byte; Designer P2 #6 topic labels. */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import fx from "./fixtures.json";
import { ScoutCard } from "../components/ScoutCard";
import { ASSET_SHORT, TOPIC_LABEL, whyFits } from "../copy";
import type { Card } from "../api/types";

const sca = fx.rec_sca.card as unknown as Card;
const civic = fx.rec_civic.card as unknown as Card;

afterEach(cleanup);

describe("claim + caveat verbatim", () => {
  it("renders card.claim byte-for-byte under Your angle", () => {
    const claim = "Generation and amplification are cheap; verification and locally named context are scarce public goods.";
    render(<ScoutCard card={{ ...civic, claim }} onHandoff={() => {}} />);
    expect(screen.getByTestId("claim").textContent).toBe(claim);
  });

  it("renders asset.caveat byte-for-byte as quiet secondary text", () => {
    const caveat = "Not published yet: an argument, not evidence.";
    const card = {
      ...civic,
      claim: civic.claim,
      asset: { ...civic.asset, caveat },
    };
    render(<ScoutCard card={card} onHandoff={() => {}} />);
    const el = screen.getByTestId("caveat");
    expect(el.textContent).toBe(caveat);
    expect(el.className).toMatch(/\bmuted\b/);
  });

  it("shows nothing when the asset has no caveat (no placeholder)", () => {
    const card = {
      ...sca,
      asset: { ...sca.asset, caveat: null },
    };
    render(<ScoutCard card={card} onHandoff={() => {}} />);
    expect(screen.queryByTestId("caveat")).toBeNull();
    expect(document.body.textContent).not.toMatch(/no caveat|caveat missing|add a caveat/i);
  });

  it("does not put a slug pill on the Today card", () => {
    render(<ScoutCard card={sca} onHandoff={() => {}} />);
    expect(screen.queryByTestId("claim-slug")).toBeNull();
    expect(document.querySelector(".slug-pill")).toBeNull();
  });
});

describe("topic human labels (Designer P2 #6)", () => {
  it("whyFits uses SCA paper + ethics label, not hyphen-swapped slug", () => {
    const line = whyFits({
      slug: "sca-pilot-ethics",
      asset: { title: "LLMs Model Non-WEIRD Populations (SCA)", asset_id: "asset_sca_nonweird" },
    });
    expect(line).toBe("Matches your SCA paper: ethics of synthetic-population pilots.");
    expect(line).not.toMatch(/sca pilot ethics/);
  });

  it("card why-fits shows the human topic label", () => {
    render(
      <ScoutCard
        card={{ ...sca, slug: "sca-pilot-ethics", asset: { ...sca.asset, asset_id: "asset_sca_nonweird" } }}
        onHandoff={() => {}}
      />,
    );
    expect(screen.getByTestId("why-fits").textContent).toContain(
      "Matches your SCA paper: ethics of synthetic-population pilots.",
    );
    expect(screen.getByTestId("why-fits").textContent).not.toMatch(/sca pilot ethics/i);
  });

  it("TOPIC_LABEL covers every known slug used in fixtures", () => {
    const slugs = new Set<string>();
    for (const a of fx.inventory as { slugs: string[] }[]) {
      a.slugs.forEach((s) => slugs.add(s));
    }
    for (const s of slugs) {
      expect(TOPIC_LABEL[s], `missing label for ${s}`).toBeTruthy();
      expect(TOPIC_LABEL[s]).not.toBe(s.replace(/-/g, " "));
    }
  });

  it("ASSET_SHORT covers every inventory fixture asset_id", () => {
    for (const a of fx.inventory as { asset_id: string }[]) {
      expect(ASSET_SHORT[a.asset_id], `missing short name for ${a.asset_id}`).toBeTruthy();
    }
  });
});
