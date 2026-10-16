/**
 * Wed 4:46 (2026-10-14) Designer recheck P1s: X budget 0 → secondary "Copy reply" + limit line,
 * Marketing topic labels on Today fit lines (and Work pill tooltips), no overflow at 390.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const fx = JSON.parse(fs.readFileSync(path.join(__dirname, "../src/test/fixtures.json"), "utf8"));
const REPORTS = path.join(__dirname, "../../reports");
const DAY = "2026-10-14";

const CLAIM: Record<string, string> = {   // seed_inventory.json one_line_claim, verbatim
  asset_gpt4o_weird: "GPT-4o-mini's answers to WVS-style values questions cluster close to WEIRD, especially US, values.",
  asset_econllm_lab: "Combining games, experiments, LLM agents, and complex-systems methods is a productive way to study heterogeneous behavior.",
};
const POSTS: Record<string, [string, string, string]> = {
  "gpt4o-weird": ["asset_gpt4o_weird", "@fixture_user_25", "Ran GPT-4o-mini through the WVS items again. Answers sit right next to the US and UK on the cultural map."],
  "econllm-lab": ["asset_econllm_lab", "@fixture_user_26", "Anyone combining lab games with LLM agents to study heterogeneous behavior? Looking for setups that go beyond prompts."],
  "abm-nroy-policy": ["asset_econllm_lab", "@fixture_user_27", "Calibrating our policy ABM gives a whole set of plausible worlds, not one. How do you report that to a ministry?"],
};

function cards() {
  const base = fx.rec_sca.card;
  return Object.entries(POSTS).map(([slug, [aid, author, text]], i) => {
    const asset = fx.inventory.find((a: any) => a.asset_id === aid) ?? base.asset;
    return {
      ...base, card_id: `card_w446_${i}`, slug, slugs: [slug], asset: { ...asset, caveat: null }, caveat: null,
      door: "EconLLM", outlet: "x", author, post_text: text, age: `${i + 2} hours ago`, url: `https://x.com/${author.slice(1)}/status/10${i}`,
      claim: CLAIM[aid], no_draft: i !== 0, copy_enabled: i === 0, handoff_blocked: null,
      draft: i === 0 ? "On the WVS map, our runs put GPT-4o-mini closer to WEIRD answers than its users. Worth checking per question." : null,
      no_draft_line: i === 0 ? null : "No draft: the basic drafter can only repeat your claim, so this one is left blank.",
    };
  });
}

function trace(c: any) {
  return {
    card_id: c.card_id, state: "open",
    source: { url: c.url, status_id: "9000000000000000915", author: c.author, text: c.post_text, card_created_at: "2026-10-14T15:30:47+00:00", age: c.age },
    grade: { asset_id: c.asset.asset_id, asset_title: c.asset.title, slugs: c.slugs, claim: c.claim, fit_level: null, filter_source: "word",
      shadow_level: "topic", labels: [], cached_grades: [{ asset_id: c.asset.asset_id, level: "topic", model: "deepseek/deepseek-v4-flash" }],
      shadow_disagreements: [] },
    score: { S: c.S, factors: c.factors, note: "" },
    draft: { model: "local_template", status: "ok", code: null, gate: { ok: false, reasons: [{ code: "claim_overlap", message: "" }] },
      shown: "", no_draft_line: c.no_draft_line, copy_enabled: false, handoff_blocked: null },
    events: [{ ts: "2026-10-14T15:30:47+00:00", kind: "discovered" }, { ts: "2026-10-14T15:30:47+00:00", kind: "scored", S: c.S },
      { ts: "2026-10-14T15:30:47+00:00", kind: "decision", decision: "enqueue" }],
  };
}

async function mock(page: Page, xLeft: number) {
  await page.route((u) => u.pathname === "/api" || u.pathname.startsWith("/api/"), async (route) => {
    const p = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    const cs = cards();
    const inventory = fx.inventory.map((a: any) => a.asset_id === "asset_econllm_lab"
      ? { ...a, slugs: [...a.slugs, "abm-nroy-policy"] } : a);
    const status = {
      x_last_checked: { at: null, sentence: "X was last checked 12 minutes ago.", run_id: null },
      drafting_ok: true, drafting_reason: "Drafting works.", xbrief_selfcheck: { ok: false, note: "" },
      queue_size: cs.length, queue_by_outlet: { x: cs.length, linkedin: 0 }, queue_sentence: `${cs.length} cards waiting in the queue.`,
    };
    const body: unknown =
      p === "/inventory" ? inventory
      : p === "/queue" ? { ...fx.queue, cards: cs, later: [], selected_asset: null, cap: { x: "7/7", linkedin: "0/7" },
          replies_today: { x: { used: 7 - xLeft, max: 7, left: xLeft }, linkedin: { used: 0, max: 7, left: 7 } } }
      : p.startsWith("/cards/") && p.endsWith("/trace") ? trace(cs.find((c) => p.includes(c.card_id)) ?? cs[0])
      : p === "/wins" ? [] : p === "/health" ? { ok: true } : p === "/status" ? status : p === "/handoff" ? [] : {};
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

for (const vp of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  test.describe(`Wed 4:46 ${vp.width}x${vp.height}`, () => {
    test.use({ viewport: vp });

    test("budget zero: X primary becomes secondary Copy reply with the limit line", async ({ page }) => {
      fs.mkdirSync(REPORTS, { recursive: true });
      await page.addInitScript(() => localStorage.setItem("ms.onboarding.done", "1"));
      await mock(page, 0);
      await page.goto("/");
      await expect(page.getByTestId("card")).toHaveCount(3);
      await expect(page.getByTestId("status-line")).toContainText("X: 0 of 7 left");
      await expect(page.getByTestId("cta-handoff")).toHaveCount(0);
      const copy = page.getByTestId("cta-copy-only").first();
      await expect(copy).toHaveText("Copy reply");
      await expect(copy).toHaveClass(/secondary/);
      await expect(copy).toBeEnabled();
      await expect(page.getByTestId("cta-copy-only").nth(1)).toBeDisabled();   // no draft → nothing to copy
      const lim = page.getByTestId("cta-limit").first();
      await expect(lim).toHaveText("X limit reached for today");
      const [b, l] = [await copy.boundingBox(), await lim.boundingBox()];
      expect(l!.y).toBeGreaterThanOrEqual(b!.y + b!.height - 1);       // beneath the button
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(vp.width);
      await expect(page.getByTestId("why-fits").first()).toContainText("GPT-4o-mini leaning toward WEIRD values");
      await expect(page.getByTestId("why-fits").nth(1)).toContainText("games, experiments, LLM agents and complex systems");
      await expect(page.getByTestId("why-fits").nth(2)).toContainText("plausible policy worlds (NROY ranges)");
      await page.getByTestId("card").first().scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(REPORTS, `w446-budget-zero-${vp.width}x${vp.height}-${DAY}.png`), fullPage: true });
    });

    test("budget left: normal primary, labels on Today", async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem("ms.onboarding.done", "1"));
      await mock(page, 4);
      await page.goto("/");
      await expect(page.getByTestId("status-line")).toContainText("X: 4 of 7 left");
      await expect(page.getByTestId("cta-handoff").first()).toHaveText("Copy reply & open on X");
      await expect(page.getByTestId("cta-limit")).toHaveCount(0);
      await page.screenshot({ path: path.join(REPORTS, `w446-today-labels-${vp.width}x${vp.height}-${DAY}.png`), fullPage: true });
    });

    test("Work: topic pills carry the label as a tooltip", async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem("ms.onboarding.done", "1"));
      await mock(page, 4);
      await page.goto("/");
      await page.getByRole("button", { name: /work/i }).first().click();
      const pill = page.locator('[data-testid=work-slug]', { hasText: "abm-nroy-policy" });
      await expect(pill).toHaveAttribute("title", "plausible policy worlds (NROY ranges)");
      await expect(page.locator('[data-testid=work-slug]', { hasText: "econllm-lab" })).toHaveAttribute("title", "games, experiments, LLM agents and complex systems");
      await page.screenshot({ path: path.join(REPORTS, `w446-work-labels-${vp.width}x${vp.height}-${DAY}.png`), fullPage: true });
    });
  });
}

for (const vp of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  test.describe(`Wed 4:46 trace ${vp.width}x${vp.height}`, () => {
    test.use({ viewport: vp });
    test("trace panel: collapsed, opens to source → fit → score → draft → log", async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem("ms.onboarding.done", "1"));
      await mock(page, 4);
      await page.goto("/");
      const panel = page.getByTestId("trace-panel").nth(1);
      await expect(panel).not.toHaveAttribute("open", "");
      await panel.locator("summary").click();
      await expect(panel.getByTestId("trace-step-grade")).toContainText("games, experiments, LLM agents and complex systems");
      await expect(panel.getByTestId("trace-step-draft")).toContainText("check: claim_overlap");
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(vp.width);
      // P2: sticky chip row is solid paper with a 1px rule
      const chips = await page.getByTestId("selected-asset").evaluate((el) => {
        const probe = document.createElement("div");
        probe.style.background = "var(--paper)";
        document.body.appendChild(probe);
        const paper = getComputedStyle(probe).backgroundColor;
        probe.remove();
        const cs = getComputedStyle(el);
        return [cs.backgroundColor === paper, cs.borderBottomWidth, cs.borderBottomStyle];
      });
      expect(chips).toEqual([true, "1px", "solid"]);
      await panel.scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(REPORTS, `w446-trace-open-${vp.width}x${vp.height}-${DAY}.png`) });
    });
  });
}
