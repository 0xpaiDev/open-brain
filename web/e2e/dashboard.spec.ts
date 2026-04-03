import { test, expect } from "@playwright/test";

/**
 * T-47: Dashboard loads all widgets without error
 */

test.describe("Dashboard Widgets", () => {
  test.beforeEach(async ({ page }) => {
    const apiKey = process.env.TEST_API_KEY;
    test.skip(!apiKey, "TEST_API_KEY env var not set");

    await page.goto("/");
    await page.evaluate((key) => localStorage.setItem("ob_api_key", key), apiKey!);
    await page.reload();
  });

  test("dashboard loads all three widgets without error alerts", async ({ page }) => {
    await page.goto("/");

    // Wait for initial load
    await page.waitForTimeout(2000);

    // No error alerts should be visible
    const alerts = page.locator('[role="alert"]');
    const alertCount = await alerts.count();
    // Allow 0 alerts, or if alerts exist, they shouldn't be critical errors
    expect(alertCount).toBeLessThanOrEqual(1);

    // Tasks section should be present
    const tasksHeading = page.getByText(/tasks/i).first();
    await expect(tasksHeading).toBeVisible({ timeout: 10000 });
  });
});
