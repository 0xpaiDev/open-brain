import { test, expect } from "@playwright/test";

/**
 * T-33: Auth flow — no key → dialog → enter key → dashboard loads
 * T-34: Auth flow — invalid key → error → re-prompt
 *
 * Prerequisites: backend API running on localhost:8000, frontend on localhost:3000.
 * Set TEST_API_KEY env var to a valid key for the running backend.
 */

test.describe("Authentication", () => {
  test.beforeEach(async ({ page }) => {
    // Clear localStorage to simulate first visit
    await page.goto("/");
    await page.evaluate(() => localStorage.clear());
    await page.reload();
  });

  test("shows auth dialog on first visit with no stored key", async ({ page }) => {
    await page.goto("/");
    // Should see the API key input
    await expect(page.getByPlaceholder(/api key/i).or(page.getByLabel(/api key/i))).toBeVisible({
      timeout: 5000,
    });
  });

  test("valid key dismisses dialog and loads dashboard", async ({ page }) => {
    const apiKey = process.env.TEST_API_KEY;
    test.skip(!apiKey, "TEST_API_KEY env var not set");

    await page.goto("/");
    const input = page.getByPlaceholder(/api key/i).or(page.getByLabel(/api key/i));
    await input.fill(apiKey!);
    await page.getByRole("button", { name: /connect|submit|save/i }).click();

    // Auth dialog should disappear
    await expect(input).not.toBeVisible({ timeout: 5000 });
  });

  test("invalid key shows error and allows retry", async ({ page }) => {
    await page.goto("/");
    const input = page.getByPlaceholder(/api key/i).or(page.getByLabel(/api key/i));
    await input.fill("completely-wrong-key");
    await page.getByRole("button", { name: /connect|submit|save/i }).click();

    // Should see an error message
    await expect(page.getByText(/invalid|error|failed/i)).toBeVisible({ timeout: 5000 });

    // Input should still be visible for retry
    await expect(input).toBeVisible();
  });

  // ── T-48: Bad key then good key flow ──────────────────────────────────────

  test("bad key then valid key loads dashboard", async ({ page }) => {
    const apiKey = process.env.TEST_API_KEY;
    test.skip(!apiKey, "TEST_API_KEY env var not set");

    await page.goto("/");
    const input = page.getByPlaceholder(/api key/i).or(page.getByLabel(/api key/i));

    // Enter wrong key first
    await input.fill("wrong-key-123");
    await page.getByRole("button", { name: /connect|submit|save/i }).click();

    // Should see error
    await expect(page.getByText(/invalid|error|failed/i)).toBeVisible({ timeout: 5000 });

    // Now enter correct key
    await input.clear();
    await input.fill(apiKey!);
    await page.getByRole("button", { name: /connect|submit|save/i }).click();

    // Dialog should dismiss
    await expect(input).not.toBeVisible({ timeout: 5000 });
  });
});
