import { test, expect } from "@playwright/test";

/**
 * Execution Explorer E2E tests
 * Uses page.route() to mock API responses — no running backend required.
 */

const MOCK_KPIS = {
  cost_today_usd: "0.012345",
  sparkline_7d: [],
  cache_hit_rate_24h: 87.5,
  failure_count_24h: 0,
  oldest_dead_letter_age_seconds: null,
};

const MOCK_TRACE = {
  id: "trace-e2e-1",
  trigger_type: "cron",
  trigger_name: "e2e_memory_flywheel",
  status: "success",
  started_at: "2026-05-25T08:00:00Z",
  finished_at: "2026-05-25T08:01:00Z",
  duration_ms: 60000,
  total_cost_usd: "0.001234",
  total_input_tokens: 100,
  total_output_tokens: 50,
  total_cache_read_tokens: 0,
  total_cache_creation_tokens: 0,
  llm_call_count: 1,
  tool_call_count: 0,
  error_message: null,
  error_class: null,
  causal_parent_trace_id: null,
  rerun_of_trace_id: null,
};

const MOCK_TRACE_DETAIL = {
  ...MOCK_TRACE,
  trigger_metadata: null,
  cron_steps: [],
  llm_calls: [],
  tool_calls: [],
  events: [],
};

test.describe("Execution Explorer", () => {
  test.beforeEach(async ({ page }) => {
    // Set API key in localStorage so the app doesn't show the auth wall
    await page.goto("/logs");
    await page.evaluate(() =>
      localStorage.setItem("ob_api_key", "test-e2e-key"),
    );

    // Mock KPIs endpoint
    await page.route("**/v1/traces/kpis", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_KPIS),
      });
    });

    // Mock traces list endpoint
    await page.route("**/v1/traces*", async (route) => {
      // Don't intercept the detail endpoint (e.g. /v1/traces/<id>)
      const url = route.request().url();
      if (url.match(/\/v1\/traces\/[^?]+$/)) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_TRACE_DETAIL),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            items: [MOCK_TRACE],
            total: 1,
            page: 1,
            page_size: 50,
          }),
        });
      }
    });

    // Reload to pick up the mocks
    await page.reload();
  });

  test("shows Execution Explorer heading", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: "Execution Explorer" }),
    ).toBeVisible({ timeout: 10000 });
  });

  test("shows at least one trace row after mocked API response", async ({
    page,
  }) => {
    // Wait for the trace row to appear
    await expect(page.getByText("e2e_memory_flywheel")).toBeVisible({
      timeout: 10000,
    });
  });

  test("clicking a trace row opens the detail panel with Rerun button", async ({
    page,
  }) => {
    // Wait for the trace row
    const traceRow = page.getByText("e2e_memory_flywheel").first();
    await expect(traceRow).toBeVisible({ timeout: 10000 });

    // Click the row button
    await traceRow.click();

    // Detail panel should appear — look for the Rerun button
    await expect(
      page.getByRole("button", { name: /rerun/i }),
    ).toBeVisible({ timeout: 10000 });
  });
});
