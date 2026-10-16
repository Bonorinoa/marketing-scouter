/**
 * Designer P1 (2026-10-13 AM): post-first cards, 390 scrollWidth, no_lens, check-error, screenshots.
 */
import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const fx = JSON.parse(fs.readFileSync(path.join(__dirname, "../src/test/fixtures.json"), "utf8"));
const REPORTS = path.join(__dirname, "../../reports");
const DAY = "2026-10-13";

function withPost(card: Record<string, unknown>) {
  return {
    ...card,
    author: card.author ?? "@fixture_user_23",
    post_text: card.post_text ?? "Are LLM synthetic participants just WEIRD? non-WEIRD cultural agent results",
    age: card.age ?? "3 hours ago",
  };
}

async function mock(page: Page, world: "full" | "empty" | "nolens" | "error") {
  await page.route((u) => u.pathname === "/api" || u.pathname.startsWith("/api/"), async (route) => {
    const u = new URL(route.request().url());
    const p = u.pathname.replace(/^\/api/, "");
    const aid = u.searchParams.get("asset_id");
    let cards = [withPost(fx.rec_sca.card), withPost(fx.rec_civic.card), withPost(fx.rec_civic_mix.card)]
      .filter((c: any) => !aid || c.asset.asset_id === aid);
    if (world === "empty") cards = [];
    if (world === "nolens") {
      cards = [withPost({ ...fx.rec_civic.card, draft: null, handoff_blocked: "no_lens" })];
    }
    let recommendBody: unknown = fx.rec_sca;
    let recommendStatus = 200;
    if (p === "/recommend" && route.request().method() === "POST") {
      if (world === "error") {
        recommendBody = { code: "link_only", message: "Paste the post text too.", error: "link_only" };
        recommendStatus = 422;
      } else {
        try {
          const b = JSON.parse(route.request().postData() || "{}");
          const snip = String(b.snippet || "").trim();
          if (!snip || /^https?:\/\/\S+$/i.test(snip)) {
            recommendBody = { code: "link_only", message: "Paste the post text too.", error: "link_only" };
            recommendStatus = 422;
          }
        } catch { /* ignore */ }
      }
    }
    const status = {
      x_last_checked: { at: null, sentence: "X was last checked just now.", run_id: null },
      drafting_ok: true, drafting_reason: "Drafting works.", xbrief_selfcheck: { ok: false, note: "" },
      queue_size: cards.length, queue_by_outlet: { x: cards.length, linkedin: 0 },
      queue_sentence: `${cards.length} cards waiting in the queue.`,
    };
    const body: unknown =
      p === "/inventory" ? (world === "empty" ? [] : fx.inventory)
      : p === "/queue" ? { ...fx.queue, cards, later: [], selected_asset: null, cap: { x: `${Math.min(cards.length, 7)}/7`, linkedin: "0/7" } }
      : p === "/wins" ? []
      : p === "/health" ? { ok: true }
      : p === "/status" ? status
      : p === "/recommend" ? recommendBody
      : p === "/later" && route.request().method() === "POST" ? { card_id: "x", later_until: new Date(Date.now() + 864e5).toISOString() }
      : p === "/handoff" ? []
      : {};
    await route.fulfill({ status: p === "/recommend" ? recommendStatus : 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

const shot = (page: Page, name: string, vp: { width: number; height: number }) =>
  page.screenshot({ path: path.join(REPORTS, `p1-${name}-${vp.width}x${vp.height}-${DAY}.png`), fullPage: true });

for (const vp of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  test.describe(`P1 ${vp.width}x${vp.height}`, () => {
    test.use({ viewport: vp });

    test("today-with-openings: post-first + no overflow at 390", async ({ page }) => {
      fs.mkdirSync(REPORTS, { recursive: true });
      await page.addInitScript(() => localStorage.setItem("ms.onboarding.done", "1"));
      await mock(page, "full");
      await page.goto("/");
      await expect(page.getByTestId("post-quote").first()).toBeVisible();
      await expect(page.getByTestId("post-text").first()).toBeVisible();
      await expect(page.getByTestId("why-fits").first()).toContainText("Your angle:");
      await expect(page.getByTestId("cap-meters")).toBeVisible();
      await expect(page.getByTestId("status-line")).toContainText(/X: \d+ of 7 left/);
      // caps not in topbar
      await expect(page.locator(".topbar [data-testid=cap-meters]")).toHaveCount(0);
      if (vp.width === 390) {
        const sw = await page.evaluate(() => ({
          doc: document.documentElement.scrollWidth,
          body: document.body.scrollWidth,
          client: document.documentElement.clientWidth,
        }));
        expect(sw.doc, `documentElement.scrollWidth ${sw.doc}`).toBeLessThanOrEqual(390);
        expect(sw.body, `body.scrollWidth ${sw.body}`).toBeLessThanOrEqual(390);
      }
      await shot(page, "today-with-openings", vp);
    });

    test("today-empty", async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem("ms.onboarding.done", "1"));
      await mock(page, "empty");
      await page.goto("/");
      await expect(page.getByTestId("empty-state").first()).toBeVisible();
      await shot(page, "today-empty", vp);
    });

    test("nolens", async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem("ms.onboarding.done", "1"));
      await mock(page, "nolens");
      await page.goto("/");
      await expect(page.getByTestId("nolens-msg")).toBeVisible();
      await expect(page.getByTestId("cta-open-post")).toBeVisible();
      await expect(page.getByTestId("draft")).toHaveCount(0);
      await shot(page, "nolens", vp);
    });

    test("check-error", async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem("ms.onboarding.done", "1"));
      await mock(page, "error");
      await page.goto("/");
      await page.getByTestId("check-post").locator("summary").click();
      await page.getByTestId("paste-url").fill("https://x.com/fixture_user_60/status/1");
      await page.locator('[data-action="scout-btn"]').click();
      await expect(page.getByTestId("link-only-error")).toBeVisible();
      await expect(page.getByTestId("btn-pending")).toHaveCount(0);
      // equal segments
      await expect(page.getByTestId("outlet-x")).toBeVisible();
      await expect(page.getByTestId("outlet-linkedin")).toBeVisible();
      await shot(page, "check-error", vp);
    });
  });
}
