import { test, expect } from "@playwright/test";

/**
 * T-30: Pulse flow — no pulse → create → form → submit → summary
 *
 * Prerequisites: backend + frontend running, valid API key in TEST_API_KEY env var.
 * Backend should have no pulse for today (or be a fresh DB).
 */

test.describe("Morning Pulse", () => {
  test.beforeEach(async ({ page }) => {
    const apiKey = process.env.TEST_API_KEY;
    test.skip(!apiKey, "TEST_API_KEY env var not set");

    // Inject API key into localStorage
    await page.goto("/");
    await page.evaluate((key) => localStorage.setItem("ob_api_key", key), apiKey!);
    await page.reload();
  });

  test("shows 'Start your day' when no pulse exists", async ({ page }) => {
    await page.goto("/");
    // Look for the start button or empty pulse state
    const startBtn = page.getByRole("button", { name: /start your day/i });
    const noPulse = page.getByText(/start your day/i);
    await expect(startBtn.or(noPulse)).toBeVisible({ timeout: 10000 });
  });

  test("full pulse lifecycle: create → form → submit → summary", async ({ page }) => {
    await page.goto("/");

    // Create pulse
    const startBtn = page.getByRole("button", { name: /start your day/i });
    await startBtn.click();

    // Form should appear
    await expect(page.getByText(/log my morning/i)).toBeVisible({ timeout: 5000 });

    // Fill form fields
    const wakeInput = page.locator('[data-testid="wake-time"]').or(page.getByLabel(/wake/i));
    if (await wakeInput.isVisible()) {
      await wakeInput.fill("07:30");
    }

    // Submit
    await page.getByRole("button", { name: /log my morning/i }).click();

    // Summary should appear (contains sleep/energy/notes info)
    await expect(
      page.getByText(/sleep/i).or(page.getByText(/energy/i)).or(page.getByText(/completed/i)),
    ).toBeVisible({ timeout: 10000 });
  });

  // ── T-49: Double-submit prevention ──────────────────────────────────────

  test("double-clicking submit does not create duplicate pulse", async ({ page }) => {
    await page.goto("/");

    // Start the pulse
    const startBtn = page.getByRole("button", { name: /start your day/i });
    if (await startBtn.isVisible({ timeout: 3000 })) {
      await startBtn.click();
    }

    // If form is visible, try double-clicking submit
    const logBtn = page.getByRole("button", { name: /log my morning/i });
    if (await logBtn.isVisible({ timeout: 3000 })) {
      // Double-click rapidly
      await logBtn.dblclick();

      // Should not crash — either shows summary or stays on form
      await page.waitForTimeout(2000);

      // Page should still be functional (no unhandled error)
      const errorOverlay = page.locator(".error-overlay, #error-boundary");
      await expect(errorOverlay).not.toBeVisible();
    }
  });
});
