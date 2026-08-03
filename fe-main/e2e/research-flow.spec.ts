import { test, expect, type Page } from "@playwright/test";

/**
 * The research flow, with the backend stubbed at the network layer.
 *
 * A real run costs minutes of arXiv downloads and LLM calls, so these serve a
 * scripted SSE stream instead. What is under test is the part the unit tests
 * cannot reach: that streamed events actually drive the UI.
 */

const API = "http://127.0.0.1:8000";

/** Encode progress events as the SSE frames the backend sends. */
function sseBody(events: Array<Record<string, unknown>>): string {
  return events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
}

const COMPLETED_RESULT = {
  user_prompt: "diffusion models for pose transfer",
  topics: ["diffusion models", "pose transfer"],
  total_papers: 1,
  project_id: "e2eproject",
  saved_filepath: "data/processed_papers_e2e.json",
  processed_papers: [
    {
      paper_id: "2301.001",
      title: "DreamPose: Fashion Video Synthesis",
      authors: ["Johanna Karras"],
      published: "2023-04-12",
      pdf_url: "https://arxiv.org/pdf/2301.001",
      topic: "pose transfer",
      normalized: {
        problem: "pose_transfer",
        methods: [["diffusion", "Diffusion Models"]],
        datasets: [["ubc_fashion", "UBC Fashion"]],
      },
    },
  ],
  trends: {},
  datasets: { total_unique_datasets: 1, datasets: [] },
  suggested_papers: [{ title: "Temporal Diffusion Priors for Pose Transfer" }],
};

async function stubResearchStream(page: Page, events: Array<Record<string, unknown>>) {
  await page.route(`${API}/api/research`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: sseBody(events),
    });
  });

  // Completion triggers a graph fetch; without this it hits a dead port and
  // the completion handler throws before rendering.
  await page.route(`${API}/api/graph/**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "success",
        project_id: "e2eproject",
        graph_data: { nodes: [], edges: [] },
      }),
    });
  });
}

test.describe("home page", () => {
  test("renders the prompt entry point", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("textbox").first()).toBeVisible();
  });

  test("does not advertise a pricing page", async ({ page }) => {
    // Removed deliberately: it sold a product with no auth and no billing.
    await page.goto("/");
    await expect(page.getByRole("link", { name: /pricing/i })).toHaveCount(0);
  });

  test("offers the editor", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("link", { name: /editor/i })).toBeVisible();
  });
});

test.describe("research streaming", () => {
  test("surfaces streamed progress messages", async ({ page }) => {
    await stubResearchStream(page, [
      { status: "processing", message: "Initializing arXiv research pipeline..." },
      {
        status: "progress",
        message: "Generated 2 topics",
        result: { topics: ["diffusion models", "pose transfer"] },
      },
      { status: "completed", message: "Research pipeline completed.", result: COMPLETED_RESULT },
    ]);

    await page.goto("/");
    const input = page.getByRole("textbox").first();
    await input.fill("diffusion models for pose transfer");
    await input.press("Enter");

    // Both only reach the DOM by way of the streamed completion event.
    await expect(page.getByText(/Research Complete/i).first()).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText(/1 paper/i).first()).toBeVisible();
  });

  test("shows an error event rather than failing silently", async ({ page }) => {
    await stubResearchStream(page, [
      { status: "processing", message: "Initializing arXiv research pipeline..." },
      { status: "error", message: "arXiv is rate limiting requests" },
    ]);

    await page.goto("/");
    const input = page.getByRole("textbox").first();
    await input.fill("diffusion models");
    await input.press("Enter");

    await expect(page.getByTestId("research-error")).toContainText(/rate limiting/i, {
      timeout: 30_000,
    });
  });

  test("reports a rejected request instead of just stopping", async ({ page }) => {
    // A throttled run used to log to the console and stop the spinner, which
    // is indistinguishable from a run that simply finished with nothing.
    await page.route(`${API}/api/research`, (route) =>
      route.fulfill({
        status: 429,
        contentType: "application/json",
        body: '{"detail":"Rate limit exceeded"}',
      }),
    );

    await page.goto("/");
    const input = page.getByRole("textbox").first();
    await input.fill("diffusion models");
    await input.press("Enter");

    await expect(page.getByTestId("research-error")).toContainText(/research failed/i, {
      timeout: 30_000,
    });
  });
});

test.describe("accessibility basics", () => {
  test("every page has exactly one h1", async ({ page }) => {
    await page.goto("/");
    expect(await page.locator("h1").count()).toBeLessThanOrEqual(1);
  });

  test("interactive controls carry accessible names", async ({ page }) => {
    await page.goto("/");
    const buttons = page.getByRole("button");
    const count = await buttons.count();

    for (let i = 0; i < count; i++) {
      const button = buttons.nth(i);
      const name =
        (await button.getAttribute("aria-label")) ?? (await button.textContent());
      expect(name?.trim(), `button ${i} has no accessible name`).toBeTruthy();
    }
  });
});
