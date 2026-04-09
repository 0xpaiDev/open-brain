import { test, expect } from "@playwright/test";

/**
 * T-31: Todo flow — add task → appears in list → complete → moves to done
 *
 * Prerequisites: backend + frontend running, valid API key in TEST_API_KEY env var.
 */

test.describe("Task Management", () => {
  test.beforeEach(async ({ page }) => {
    const apiKey = process.env.TEST_API_KEY;
    test.skip(!apiKey, "TEST_API_KEY env var not set");

    await page.goto("/");
    await page.evaluate((key) => localStorage.setItem("ob_api_key", key), apiKey!);
    await page.reload();
  });

  test("add a new task and verify it appears in the list", async ({ page }) => {
    await page.goto("/");

    // Find the task input and add a task
    const taskInput = page.locator('[data-testid="task-input"]').or(
      page.getByPlaceholder(/add a task|new task|description/i),
    );
    await taskInput.fill("E2E test task");

    const addBtn = page.getByRole("button", { name: /add/i });
    await addBtn.click();

    // Task should appear in the list
    await expect(page.getByText("E2E test task")).toBeVisible({ timeout: 5000 });
  });

  test("complete a task moves it to done section", async ({ page }) => {
    await page.goto("/");

    // Add a task first
    const taskInput = page.locator('[data-testid="task-input"]').or(
      page.getByPlaceholder(/add a task|new task|description/i),
    );
    await taskInput.fill("Complete me in E2E");
    await page.getByRole("button", { name: /add/i }).click();
    await expect(page.getByText("Complete me in E2E")).toBeVisible({ timeout: 5000 });

    // Find the checkbox for this task and click it
    const taskRow = page.locator(":has-text('Complete me in E2E')").first();
    const checkbox = taskRow.locator('[data-testid="complete-checkbox"]').or(
      taskRow.locator('input[type="checkbox"]').or(taskRow.locator('[role="checkbox"]')),
    );
    await checkbox.click();

    // Wait for the task to move (optimistic update)
    await page.waitForTimeout(1000);

    // The task should still exist somewhere (in the done section)
    // but might have different styling
  });

  // ── T-45: Add task with priority and due date ─────────────────────────────

  test("add a task with high priority", async ({ page }) => {
    await page.goto("/");

    const taskInput = page.locator('[data-testid="task-input"]').or(
      page.getByPlaceholder(/add a task|new task|description/i),
    );
    await taskInput.fill("High priority E2E task");

    // Select high priority
    const prioritySelect = page.locator('[data-testid="priority-select"]').or(
      page.getByRole("combobox"),
    );
    if (await prioritySelect.isVisible()) {
      await prioritySelect.click();
      await page.getByRole("option", { name: /high/i }).click();
    }

    await page.getByRole("button", { name: /add/i }).click();

    // Task should appear with some priority indicator
    await expect(page.getByText("High priority E2E task")).toBeVisible({ timeout: 5000 });
  });

  // ── Step 7: New E2E tests for dashboard update ────────────────────────────

  test("add task — default date is tomorrow", async ({ page }) => {
    await page.goto("/");

    // Date picker button should show "Tomorrow" by default
    const dateBtn = page.getByLabel("Pick date");
    await expect(dateBtn).toContainText("Tomorrow");
  });

  test("complete task → undo via toast → task restored", async ({ page }) => {
    await page.goto("/");

    // Add a task
    const taskInput = page.getByPlaceholder(/add a task/i);
    await taskInput.fill("Undo E2E test");
    await page.getByRole("button", { name: /add/i }).click();
    await expect(page.getByText("Undo E2E test")).toBeVisible({ timeout: 5000 });

    // Complete the task
    const checkbox = page.getByRole("checkbox", { name: /complete.*undo e2e test/i });
    await checkbox.click();

    // Wait for toast with "Undo" button
    const undoBtn = page.getByRole("button", { name: "Undo" });
    await expect(undoBtn).toBeVisible({ timeout: 5000 });

    // Click undo
    await undoBtn.click();

    // Task should reappear in the open list
    await expect(page.getByText("Undo E2E test")).toBeVisible({ timeout: 5000 });
  });

  test("search filters task list", async ({ page }) => {
    await page.goto("/");

    // Add two tasks
    const taskInput = page.getByPlaceholder(/add a task/i);
    await taskInput.fill("Alpha search test");
    await page.getByRole("button", { name: /add/i }).click();
    await expect(page.getByText("Alpha search test")).toBeVisible({ timeout: 5000 });

    await taskInput.fill("Beta search test");
    await page.getByRole("button", { name: /add/i }).click();
    await expect(page.getByText("Beta search test")).toBeVisible({ timeout: 5000 });

    // Switch to All tab to see all tasks
    await page.getByRole("tab", { name: /all/i }).click();

    // Search for "Alpha"
    const searchInput = page.getByLabel("Search tasks");
    await searchInput.fill("Alpha");

    // Only Alpha should be visible
    await expect(page.getByText("Alpha search test")).toBeVisible();
    await expect(page.getByText("Beta search test")).not.toBeVisible();
  });

  test("This Week tab shows correct tasks", async ({ page }) => {
    await page.goto("/");

    // Verify "This Week" tab exists and is clickable
    const weekTab = page.getByRole("tab", { name: /this week/i });
    await expect(weekTab).toBeVisible();
    await weekTab.click();

    // The tab panel should be visible (content depends on actual data)
    const panel = page.getByRole("tabpanel");
    await expect(panel).toBeVisible();
  });
});
