/**
 * DoR card-visibility AA check (Designer CARD-VISUAL-BRIEF §0).
 * Asserts readable size + WCAG AA contrast at 1280x800 and 390x844.
 */
import { test, expect, type Page, type Locator } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const fx = JSON.parse(fs.readFileSync(path.join(__dirname, "../src/test/fixtures.json"), "utf8"));
const REPORTS = path.join(__dirname, "../../reports");
const DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Phoenix", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());

const S9 = ["Fit", "Urgency", "FormatPrior", "Evidence", "DoorMatch", "EffortPenalty"] as const;

function relLuminance(r: number, g: number, b: number): number {
  const lin = [r, g, b].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}

function parseColor(css: string): [number, number, number, number] | null {
  const m = css.match(/rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)/i);
  if (!m) return null;
  return [Number(m[1]), Number(m[2]), Number(m[3]), m[4] === undefined ? 1 : Number(m[4])];
}

function contrastRatio(fg: [number, number, number], bg: [number, number, number]): number {
  const L1 = relLuminance(fg[0], fg[1], fg[2]);
  const L2 = relLuminance(bg[0], bg[1], bg[2]);
  const hi = Math.max(L1, L2);
  const lo = Math.min(L1, L2);
  return (hi + 0.05) / (lo + 0.05);
}

async function effectiveBg(page: Page, el: Locator): Promise<[number, number, number]> {
  return el.evaluate((node) => {
    let cur: Element | null = node as Element;
    while (cur) {
      const bg = getComputedStyle(cur).backgroundColor;
      const m = bg.match(/rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)/i);
      if (m) {
        const a = m[4] === undefined ? 1 : Number(m[4]);
        if (a >= 0.95) return [Number(m[1]), Number(m[2]), Number(m[3])] as [number, number, number];
      }
      cur = cur.parentElement;
    }
    return [247, 245, 240] as [number, number, number]; // --paper fallback
  });
}

async function assertReadable(page: Page, loc: Locator, label: string) {
  await expect(loc, label).toBeVisible();
  await loc.scrollIntoViewIfNeeded();
  const box = await loc.boundingBox();
  expect(box, `${label} has box`).toBeTruthy();
  expect(box!.height, `${label} height`).toBeGreaterThan(0);
  const fontSize = await loc.evaluate((n) => parseFloat(getComputedStyle(n).fontSize));
  expect(fontSize, `${label} font-size`).toBeGreaterThanOrEqual(11);

  // Not clipped by overflow:hidden ancestors (sticky overlays excluded after scrollIntoView).
  const clipped = await loc.evaluate((n) => {
    const r = n.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return true;
    let cur: HTMLElement | null = n as HTMLElement;
    while (cur && cur !== document.body) {
      const st = getComputedStyle(cur);
      const oy = st.overflowY;
      const ox = st.overflowX;
      if ((oy === "hidden" || oy === "clip" || ox === "hidden" || ox === "clip") && cur !== n) {
        const cr = cur.getBoundingClientRect();
        // Fully outside the overflow parent → clipped
        if (r.bottom <= cr.top + 0.5 || r.top >= cr.bottom - 0.5 || r.right <= cr.left + 0.5 || r.left >= cr.right - 0.5)
          return true;
      }
      cur = cur.parentElement;
    }
    // Still in viewport (after scrollIntoView)
    const vh = window.innerHeight, vw = window.innerWidth;
    if (r.bottom <= 0 || r.top >= vh || r.right <= 0 || r.left >= vw) return true;
    return false;
  });
  expect(clipped, `${label} not clipped`).toBe(false);

  // WCAG AA contrast for text nodes with own color
  const colorCss = await loc.evaluate((n) => getComputedStyle(n).color);
  const fg = parseColor(colorCss);
  if (fg && fg[3] >= 0.9) {
    const bg = await effectiveBg(page, loc);
    const ratio = contrastRatio([fg[0], fg[1], fg[2]], bg);
    expect(ratio, `${label} contrast ${colorCss} on bg`).toBeGreaterThanOrEqual(4.5);
  }
}

async function mockApi(page: Page) {
  const sca = fx.rec_sca.card;
  const civic = fx.rec_civic.card;
  const inventory = fx.inventory;
  // Fixture is scope-consistent: /queue?asset_id= returns only that asset's cards (same as the real API).
  const queueFor = (aid: string | null) => ({ ...fx.queue, cap: fx.queue.cap,
    cards: [sca, civic].filter((c: { asset: { asset_id: string } }) => !aid || c.asset.asset_id === aid),
    selected_asset: aid ? inventory.find((a: { asset_id: string }) => a.asset_id === aid) ?? null : null });

  // Only the Vite proxy prefix `/api/...` — never `/src/api/*.ts` modules.
  await page.route((url) => {
    const path = typeof url === "string" ? new URL(url).pathname : url.pathname;
    return path === "/api" || path.startsWith("/api/");
  }, async (route) => {
    const u = new URL(route.request().url());
    const p = u.pathname.replace(/^\/api/, "") || "/";
    let body: unknown = {};
    if (p === "/inventory" || p.endsWith("/inventory")) body = inventory;
    else if (p === "/queue" || p.endsWith("/queue")) body = queueFor(u.searchParams.get("asset_id"));
    else if (p === "/wins" || p.endsWith("/wins")) body = [];
    else if (p === "/health" || p.endsWith("/health")) body = { ok: true };
    else if (p === "/recommend" || p.endsWith("/recommend")) body = fx.rec_civic;
    else if (p === "/status" || p.endsWith("/status")) body = { x_last_checked: { at: null, sentence: "X hasn't been checked yet.", run_id: null }, drafting_ok: true, drafting_reason: "Drafting works.", xbrief_selfcheck: { ok: false, note: "" }, queue_size: 2, queue_by_outlet: { x: 1, linkedin: 1 }, queue_sentence: "2 cards waiting in the queue." };
    else if (p === "/handoff" || p.endsWith("/handoff")) body = fx.handoff_civic;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

async function prepareQueue(page: Page) {
  await page.addInitScript(() => localStorage.setItem("ms.onboarding.done", "1"));
  await page.goto("/");
  await expect(page.getByTestId("banner")).toBeVisible();
  // All-interests mode: both doors' cards are legitimately in the Queue.
  await page.getByRole("button", { name: /^Today/ }).click();
  await expect(page.getByTestId("today")).toBeVisible();
  await expect(page.getByTestId("card").first()).toBeVisible();
}

async function runViewportChecks(page: Page, viewport: { width: number; height: number }, shotName: string) {
  await page.setViewportSize(viewport);
  await prepareQueue(page);

  await assertReadable(page, page.getByTestId("banner"), "banner");
  for (const f of S9) {
    const locs = page.getByTestId(`s9-${f}`);
    expect(await locs.count(), `s9-${f} count`).toBeGreaterThanOrEqual(1);
    // Check first of each factor (both cards have all six)
    await assertReadable(page, locs.first(), `s9-${f}`);
  }
  // Soft evidence
  const soft = page.locator('[data-testid="evidence"][data-evidence="soft_pending"]').first();
  await assertReadable(page, soft, "evidence soft_pending");
  // Soft must not use success green token --ev-a (assert against known RGB 46,107,63)
  const softColor = await soft.evaluate((n) => getComputedStyle(n).color);
  const softParsed = parseColor(softColor)!;
  expect(
    softParsed[0] === 46 && softParsed[1] === 107 && softParsed[2] === 63,
    `soft evidence must not be --ev-a green (got ${softColor})`,
  ).toBe(false);

  // Both door badges
  const doors = page.getByTestId("door-badge");
  expect(await doors.count()).toBeGreaterThanOrEqual(2);
  const doorTexts = await doors.allTextContents();
  expect(doorTexts.some((t) => t.includes("Research voice"))).toBe(true);
  expect(doorTexts.some((t) => t.includes("Civic voice"))).toBe(true);
  await assertReadable(page, doors.first(), "door-badge-0");
  await assertReadable(page, doors.nth(1), "door-badge-1");

  const likes = page.getByTestId("likes-info").first();
  await assertReadable(page, likes, "likes-info");

  // Promote Adepa: strip shows its tone and the Queue narrows to its card only (scope-bug regression).
  await page.getByTestId("asset-select").selectOption("asset_adepa_lagaceta_carta");
  await expect(page.getByTestId("card")).toHaveCount(1);
  await expect(page.getByTestId("card").first()).toHaveAttribute("data-door", "Augusto-civic");
  await assertReadable(page, page.getByTestId("selected-asset"), "selected-asset");
  // Designer 13:10: mobile Promoting row is title-only (tone stays on the card + tooltip); check sticky tone at desktop only
  if (viewport.width > 560) await assertReadable(page, page.getByTestId("sa-tone"), "sa-tone");
  else await assertReadable(page, page.getByTestId("card-asset-tone").first(), "card-asset-tone (mobile)");
  await assertReadable(page, page.getByTestId("api-status"), "api-status");

  fs.mkdirSync(REPORTS, { recursive: true });
  const shotPath = path.join(REPORTS, shotName);
  await page.screenshot({ path: shotPath, fullPage: true });
  return shotPath;
}

test.describe("card visibility AA", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page);
  });

  test("1280x800 readable + AA", async ({ page }) => {
    const shot = await runViewportChecks(page, { width: 1280, height: 800 }, `card-visual-1280x800-${DAY}.png`);
    expect(fs.existsSync(shot)).toBe(true);
  });

  test("390x844 readable + AA", async ({ page }) => {
    const shot = await runViewportChecks(page, { width: 390, height: 844 }, `card-visual-390x844-${DAY}.png`);
    expect(fs.existsSync(shot)).toBe(true);
  });
});
