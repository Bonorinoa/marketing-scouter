/** UX foundations at both sizes: purpose + empty state per tab, onboarding, health dot, outcome panel, drawer.
 *  Saves a screenshot of every view to reports/ (views-<view>-<WxH>-<day>.png). */
import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const fx = JSON.parse(fs.readFileSync(path.join(__dirname, "../src/test/fixtures.json"), "utf8"));
const REPORTS = path.join(__dirname, "../../reports");
const DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Phoenix", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());

async function mock(page: Page, world: "full" | "empty" | "offline" | "killed") {
  let sealed = false;
  await page.route((u) => u.pathname === "/api" || u.pathname.startsWith("/api/"), async (route) => {
    if (world === "offline") return route.abort("connectionrefused");
    const u = new URL(route.request().url());
    const p = u.pathname.replace(/^\/api/, "");
    const aid = u.searchParams.get("asset_id");
    const cards = world === "empty" ? [] : [fx.rec_sca.card, fx.rec_civic.card, fx.rec_civic_mix.card].filter((c) => !aid || c.asset.asset_id === aid);
    let recommendBody: unknown = world === "killed" ? fx.rec_kill : fx.rec_sca;
    let recommendStatus = 200;
    if (p === "/recommend" && route.request().method() === "POST") {
      try {
        const b = JSON.parse(route.request().postData() || "{}");
        const snip = String(b.snippet || "").trim();
        if (!snip || /^https?:\/\/\S+$/i.test(snip)) {
          recommendBody = { code: "link_only", message: "Paste the post text too.", error: "link_only" };
          recommendStatus = 422;
        }
      } catch {}
    }
    const status = {
      x_last_checked: { at: null, sentence: "X hasn't been checked yet.", run_id: null },
      drafting_ok: true, drafting_reason: "Drafting works.", xbrief_selfcheck: { ok: false, note: "" },
      queue_size: cards.length, queue_by_outlet: { x: cards.length, linkedin: 0 },
      queue_sentence: `${cards.length} cards waiting in the queue.`,
    };
    const body: unknown =
      p === "/inventory" ? (world === "empty" ? [] : fx.inventory)
      : p === "/queue" ? { ...fx.queue, cards, selected_asset: null }
      : p === "/wins" ? []
      : p === "/health" ? { ok: true }
      : p === "/status" ? status
      : p === "/recommend" ? recommendBody
      : p === "/handoff" && route.request().method() === "POST" ? ((sealed = true), fx.handoff_sca)
      : p === "/handoff" ? (sealed ? [{ ...fx.handoff_sca, status: "pending", expires_at: fx.handoff_sca.payload.expires_at, asset_title: "SCA paper" }] : [])
      : {};
    await route.fulfill({ status: p === "/recommend" ? recommendStatus : 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}
const shot = (page: Page, name: string, vp: { width: number; height: number }, fullPage = true) =>
  page.screenshot({ path: path.join(REPORTS, `views-${name}-${vp.width}x${vp.height}-${DAY}.png`), fullPage });

for (const vp of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  test.describe(`views ${vp.width}x${vp.height}`, () => {
    test.use({ viewport: vp });

    test("first run: onboarding + empty states on every tab", async ({ page }) => {
      fs.mkdirSync(REPORTS, { recursive: true });
      await mock(page, "empty");
      await page.goto("/");
      await expect(page.getByTestId("onboarding")).toBeVisible();
      await expect(page.getByTestId("api-status")).toHaveAttribute("data-health", "ok");
      await shot(page, "first-run", vp);
      await page.getByRole("button", { name: "Got it", exact: true }).click();
      for (const [tab, name] of [["Today", "today-empty"], ["Work", "work-empty"], ["Wins", "wins-empty"]]) {
        await page.getByRole("button", { name: tab, exact: true }).click();
        await expect(page.getByTestId("tab-purpose")).toBeVisible();
        await expect(page.getByTestId("empty-state").first()).toBeVisible();
        await shot(page, name, vp);
      }
    });

    test("full: assets, scout outcome, queue, handoff drawer", async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem("ms.onboarding.done", "1"));
      await mock(page, "full");
      await page.goto("/");
      await expect(page.getByTestId("today")).toBeVisible();
      await expect(page.getByTestId("nav-count-today")).toHaveText("3");
      await shot(page, "today-with-openings", vp);
      if (vp.width === 390) {
        // Designer 13:10: ≤96px of chrome (banner excluded) before the first card on mobile
        const top = await page.getByTestId("card").first().boundingBox();
        const ban = await page.getByTestId("banner").boundingBox();
        const status = await page.getByTestId("status-line").boundingBox();
        fs.writeFileSync(path.join(REPORTS, `_mobile_chrome-${DAY}.json`), JSON.stringify({ firstCardTop: top?.y, bannerBottom: (ban?.y ?? 0) + (ban?.height ?? 0), statusTop: status?.y, topbar: await page.locator(".topbar").boundingBox(), sel: await page.getByTestId("selected-asset").boundingBox() }));
        expect((status?.y ?? 0) - ((ban?.y ?? 0) + (ban?.height ?? 0))).toBeLessThanOrEqual(96);
      }
      await page.getByRole("button", { name: /^Work/ }).click();
      await shot(page, "work", vp);
      await page.getByText("Add an asset", { exact: true }).first().click(); // Designer PM #10: titled panel
      await expect(page.getByTestId("aa-surface")).toBeVisible();
      await shot(page, "add-asset", vp);
      await page.getByRole("button", { name: /^Today/ }).click();
      await page.getByTestId("check-post").locator("summary").click();
      await page.getByTestId("paste-url").fill("https://x.com/fixture_user_60/status/1");
      await page.getByTestId("paste-snippet").fill("LLM respondents only resemble WEIRD samples");
      await page.locator('[data-action="scout-btn"]').click();
      await expect(page.getByTestId("scout-outcome")).toBeVisible();
      await expect(page.getByTestId("toast").first()).toBeVisible();
      await expect(page.locator("pre:visible")).toHaveCount(0);
      await shot(page, "scout-outcome", vp);
      // Copy reply & open (draft on card) → waiting for you; then Did you post it? opens confirm drawer
      await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
      await page.getByTestId("cta-handoff").first().click();
      await expect(page.getByTestId("waiting-receipts")).toBeVisible();
      await expect(page.getByTestId("await-pill").first()).toBeVisible();
      await page.getByTestId("waiting-open").click();
      await expect(page.getByTestId("handoff-panel")).toBeVisible();
      await expect(page.locator("pre:visible")).toHaveCount(0);
      await shot(page, "handoff", vp, false);
      await page.getByRole("button", { name: "Close" }).click();
      await page.reload();
      await page.getByRole("button", { name: /^Today/ }).click();
      await expect(page.getByTestId("waiting-item")).toHaveCount(1);
      await expect(page.locator('[data-code="no_lens"]')).toBeVisible();
      await shot(page, "today-waiting", vp);
    });

    test("killed: plain reason stays on screen", async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem("ms.onboarding.done", "1"));
      await mock(page, "killed");
      await page.goto("/");
      await page.getByTestId("check-post").locator("summary").click();
      await page.getByTestId("paste-url").fill("https://x.com/fixture_user_63/status/2");
      await page.getByTestId("paste-snippet").fill("totally unrelated gardening tips for spring");
      await page.locator('[data-action="scout-btn"]').click();
      await expect(page.getByTestId("killed-card")).toContainText("Nothing was queued.");
      await page.waitForTimeout(500);
      await expect(page.getByTestId("killed-card")).toBeVisible();
      await shot(page, "scout-killed", vp);
    });


    test("check-post link-only shows plain error", async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem("ms.onboarding.done", "1"));
      await mock(page, "full");
      await page.goto("/");
      await page.getByTestId("check-post").locator("summary").click();
      await page.getByTestId("paste-url").fill("https://x.com/fixture_user_60/status/99");
      // leave snippet empty → link_only
      await page.locator('[data-action="scout-btn"]').click();
      await expect(page.getByTestId("link-only-error")).toContainText("Couldn't read that post. Paste its text.");
      await shot(page, "check-post-link-only", vp);
    });

    test("offline: red status, actions disabled", async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem("ms.onboarding.done", "1"));
      await mock(page, "offline");
      await page.goto("/");
      await expect(page.getByTestId("api-status")).toHaveAttribute("data-health", "offline");
      await page.getByTestId("check-post").locator("summary").click();
      await expect(page.locator('[data-action="scout-btn"]')).toBeDisabled();
      await shot(page, "offline", vp);
    });
  });
}
