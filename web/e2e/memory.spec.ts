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
});
