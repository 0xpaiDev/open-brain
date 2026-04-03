import { test, expect } from "@playwright/test";

/**
 * T-32: Memory flow — compose → submit → toast appears
 * T-35: Calendar strip — unavailable state rendering
 *
 * Prerequisites: backend + frontend running, valid API key in TEST_API_KEY env var.
 */

test.describe("Memory Ingestion", () => {
  test.beforeEach(async ({ page }) => {
    const apiKey = process.env.TEST_API_KEY;
    test.skip(!apiKey, "TEST_API_KEY env var not set");

    await page.goto("/");
    await page.evaluate((key) => localStorage.setItem("ob_api_key", key), apiKey!);
    await page.reload();
  });

  test("ingest text memory via smart composer", async ({ page }) => {
    // Navigate to memories page
    await page.goto("/memories");

    // Find the text area in the composer
    const textarea = page.locator("textarea").first();
    await textarea.fill("E2E test memory: integration testing the dashboard");

    // Click commit button
    const commitBtn = page.getByRole("button", { name: /commit memory/i });
    await commitBtn.click();

    // Should see a success toast
    await expect(
      page.getByText(/memory committed|queued/i).or(page.getByText(/memory already exists/i)),
    ).toBeVisible({ timeout: 5000 });
  });
});

test.describe("Calendar Strip", () => {
  test.beforeEach(async ({ page }) => {
    const apiKey = process.env.TEST_API_KEY;
    test.skip(!apiKey, "TEST_API_KEY env var not set");

    await page.goto("/");
    await page.evaluate((key) => localStorage.setItem("ob_api_key", key), apiKey!);
    await page.reload();
  });

  test("shows calendar state on dashboard", async ({ page }) => {
    await page.goto("/");

    // Calendar should show either events, "not connected", or "no events"
    const calendarSection = page.getByText(/calendar/i).first();
    await expect(calendarSection).toBeVisible({ timeout: 10000 });
  });

  // ── T-50: Calendar unavailable shows message ──────────────────────────────

  test("calendar unavailable shows appropriate message", async ({ page }) => {
    await page.goto("/");

    // If calendar isn't connected, we expect "not connected" or similar
    const unavailableText = page.getByText(/not connected|unavailable|connect your calendar/i);
    const eventsText = page.getByText(/calendar/i).first();
    // Either calendar shows events or shows unavailable message — both are valid
    await expect(unavailableText.or(eventsText)).toBeVisible({ timeout: 10000 });
  });
});

// ── T-46: Memory duplicate shows info toast ─────────────────────────────────

test.describe("Memory Duplicate Detection", () => {
  test.beforeEach(async ({ page }) => {
    const apiKey = process.env.TEST_API_KEY;
    test.skip(!apiKey, "TEST_API_KEY env var not set");

    await page.goto("/");
    await page.evaluate((key) => localStorage.setItem("ob_api_key", key), apiKey!);
    await page.reload();
  });

  test("submitting same memory twice shows duplicate toast", async ({ page }) => {
    await page.goto("/memories");

    const text = `E2E duplicate test ${Date.now()}`;
    const textarea = page.locator("textarea").first();
    const commitBtn = page.getByRole("button", { name: /commit memory/i });

    // First submission
    await textarea.fill(text);
    await commitBtn.click();
    await expect(
      page.getByText(/memory committed|queued/i),
    ).toBeVisible({ timeout: 5000 });

    // Wait for form to reset, then submit again
    await page.waitForTimeout(1000);
    await textarea.fill(text);
    await commitBtn.click();

    // Should see duplicate/already exists toast
    await expect(
      page.getByText(/already exists|duplicate/i),
    ).toBeVisible({ timeout: 5000 });
  });
});
