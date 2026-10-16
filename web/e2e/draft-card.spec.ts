/** In-app x-brief draft on the handoff card, fully mocked /api (never real x-brief, never the live API).
 *  Screenshots: reports/draft-card-<state>-<WxH>.png */
import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const fx = JSON.parse(fs.readFileSync(path.join(__dirname, "../src/test/fixtures.json"), "utf8"));
const REPORTS = path.join(__dirname, "../../reports");
const HID = fx.handoff_sca.payload.handoff_id;
const MODEL = "SCA pilots show synthetic agents can track non-WEIRD behavior where human data exist. https://arxiv.org/abs/2501.06834";

type Mode = "ok" | "error" | "slow";
async function mock(page: Page, mode: Mode, counter: { drafts: number; checks: number }) {
  await page.route((u) => u.pathname === "/api" || u.pathname.startsWith("/api/"), async (route) => {
    const req = route.request(); const p = new URL(req.url()).pathname.replace(/^\/api/, ""); const m = req.method();
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(b) });
    if (p === `/handoff/${HID}/draft` && m === "POST") {
      counter.drafts++;
      if (mode === "slow") await new Promise((r) => setTimeout(r, 1500));
      if (mode === "error") return json({ code: "xbrief_timeout", message: "x-brief took too long and was stopped. Copy the handoff instead." }, 502);
      return json({ handoff_id: HID, status: "ok", draft_text: MODEL, authored_by: "model", label: "model draft", gate: { ok: true, reasons: [] },
        copy_enabled: true, warnings: [], elapsed_ms: 1500, outlet: "x", door: "EconLLM", lang: "en" });
    }
    if (p === `/handoff/${HID}/draft/check`) {
      counter.checks++;
      const t = JSON.parse(req.postData() || "{}").draft_text as string;
      const blocked = /DM me/i.test(t);
      return json({ handoff_id: HID, authored_by: t.trim() === MODEL ? "model" : "augusto_edit", copy_enabled: !blocked,
        gate: { ok: !blocked, reasons: blocked ? [{ code: "cta_bait", message: "Drop the call to action (like \"DM me\"). Let the claim do the work." }] : [] },
        warnings: /@\w+/.test(t) ? [{ code: "foreign_handle", message: "The draft mentions @fixture_user_40, who isn't in this handoff." }] : [] });
    }
    if (p === `/handoff/${HID}/draft`) return json({ handoff_id: HID, draft_text: null });
    if (p === "/xbrief/health") return json({ binary: "x-brief", present: true, doctor_ok: true, up: mode !== "error" });
    if (p === "/status") return json({ x_last_checked: { at: null, sentence: "X hasn't been checked yet.", run_id: null }, drafting_ok: true, drafting_reason: "Drafting works.", xbrief_selfcheck: { ok: false, note: "" }, queue_size: 1, queue_by_outlet: { x: 1, linkedin: 0 }, queue_sentence: "1 card waiting in the queue." });
    const body: unknown =
      p === "/inventory" ? fx.inventory
      : p === "/queue" ? { ...fx.queue, cards: [{ ...fx.rec_sca.card, draft: null }], selected_asset: null }
      : p === "/wins" ? [] : p === "/health" ? { ok: true }
      : p === "/handoff" && m === "POST" ? fx.handoff_sca
      : p === "/handoff" ? [] : {};
    return json(body);
  });
}

async function openDrawer(page: Page) {
  await page.addInitScript(() => localStorage.setItem("ms.onboarding.done", "1"));
  await page.goto("/");
  await page.getByRole("button", { name: /^Today/ }).click();
  await page.getByTestId("cta-handoff").first().click();
  await expect(page.getByTestId("handoff-panel")).toBeVisible();
}

for (const vp of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  test.describe(`draft card ${vp.width}x${vp.height}`, () => {
    test.use({ viewport: vp });
    const shot = (page: Page, name: string) => page.getByTestId("handoff-panel").screenshot({ path: path.join(REPORTS, `draft-card-${name}-${vp.width}x${vp.height}.png`) });

    test("pending → success → blocked → edit → copy, double-click starts one draft", async ({ page, context }) => {
      fs.mkdirSync(REPORTS, { recursive: true });
      await context.grantPermissions(["clipboard-read", "clipboard-write"]);
      const c = { drafts: 0, checks: 0 };
      await mock(page, "slow", c);
      await openDrawer(page);
      await expect(page.getByTestId("toast")).toHaveCount(0); // no toast while the drawer is open
      const btn = page.getByTestId("draft-start");
      await expect(btn).toHaveText("Write a draft");
      await btn.dblclick();
      await expect(btn).toBeDisabled();
      await expect(btn).toContainText("Writing a draft…");
      await expect(page.getByTestId("draft-live")).toHaveText("Writing a draft…");
      await shot(page, "pending");
      await expect(page.getByTestId("draft-text")).toHaveValue(MODEL);
      expect(c.drafts).toBe(1);
      await expect(page.getByTestId("draft-author")).toHaveText("Model draft");
      await expect(page.getByTestId("draft-count")).toContainText("/ 280");
      await shot(page, "success");
      await page.getByTestId("draft-text").fill(MODEL + " DM me @fixture_user_40");
      await expect(page.getByTestId("gate-reasons")).toContainText("Drop the call to action");
      await expect(page.getByTestId("copy-final")).toBeDisabled();
      await expect(page.getByTestId("draft-warnings")).toContainText("@fixture_user_40");
      await expect(page.getByTestId("draft-author")).toHaveText("Your edit");
      await shot(page, "blocked");
      const mine = "Agents track non-WEIRD behavior where human data exist; the paper shows where they don't. https://arxiv.org/abs/2501.06834";
      await page.getByTestId("draft-text").fill(mine);
      await expect(page.getByTestId("copy-final")).toBeEnabled();
      await page.getByTestId("copy-final").click();
      await expect(page.getByTestId("copy-final-done")).toHaveText(/^Copied for .+, EconLLM$/);
      await expect(page.getByTestId("toast")).toHaveCount(0);
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(mine);
      await shot(page, "copied");
    });

    test("x-brief error falls back to the clipboard handoff with selectable text", async ({ page }) => {
      const c = { drafts: 0, checks: 0 };
      await mock(page, "error", c);
      await openDrawer(page);
      await page.getByTestId("draft-start").click();
      await expect(page.getByTestId("draft-error")).toContainText("x-brief took too long");
      await expect(page.getByTestId("fallback-text")).toBeVisible();
      await expect(page.getByTestId("fallback-text")).toHaveValue(new RegExp(HID));
      await expect(page.getByTestId("copy-handoff")).toBeVisible();
      await shot(page, "error-fallback");
    });
  });
}
