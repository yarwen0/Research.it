import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const tags = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const fixtureTime = 1795305600000;
const result = {
  id: "a11y-result", timestamp: fixtureTime, prompt: "Accessible research interfaces",
  user_prompt: "Accessible research interfaces", topics: ["accessibility"], total_papers: 1,
  project_id: "a11yproject", saved_filepath: "data/a11y.json", speedMode: "fast",
  processed_papers: [{ paper_id: "paper1", title: "Accessible research interfaces", authors: ["Example Researcher"], published: "2024-01-01", pdf_url: "https://example.com/paper.pdf", topic: "accessibility", normalized: { methods: [["keyboard", "Keyboard Navigation"]], datasets: [] } }],
  suggested_papers: [{ title: "Keyboard access to citation networks", keywords: ["accessibility"], abstract: "An example research suggestion used to exercise the results interface." }],
  trends: {}, datasets: { total_unique_datasets: 0, datasets: [] },
  progressUpdates: [{ status: "completed", message: "Research pipeline completed.", timestamp: fixtureTime }],
};
const review = {
  id: "a11y-review", paperTitle: "Accessible research interfaces", paperIndex: 0,
  savedFilepath: "data/a11y.json", latexContent: "\\documentclass{article}\n\\begin{document}\nAccessible research\n\\end{document}",
  bibliography: [{ title: "Accessible research interfaces", authors: ["Example Researcher"], year: 2024 }],
  status: "completed", createdAt: fixtureTime, updatedAt: fixtureTime,
};

async function seed(page: Page, theme: string) {
  await page.addInitScript(({ result, review, theme }) => {
    localStorage.setItem("theme", theme);
    localStorage.setItem("research_responses", JSON.stringify([result]));
    localStorage.setItem("review-store-data", JSON.stringify({ reviews: [[review.id, review]], currentReviewId: review.id }));
  }, { result, review, theme });
  await page.route("http://127.0.0.1:8000/api/research", route => route.fulfill({
    contentType: "text/event-stream",
    body: `data: ${JSON.stringify({ status: "completed", message: "Research pipeline completed.", result })}\n\n`,
  }));
}

test("all app routes meet WCAG 2.2 AA", async ({ browser }, testInfo) => {
  test.setTimeout(300_000);
  const phase = process.env.A11Y_PHASE;
  if (phase && !["baseline", "after"].includes(phase)) throw new Error("Invalid A11Y_PHASE");
  const scans: Array<Record<string, unknown>> = [];
  const failures: string[] = [];
  const cases = [
    { route: "/", state: "initial" },
    { route: "/", state: "speed-menu" },
    { route: "/", state: "research-complete" },
    { route: "/editor", state: "edit" },
    { route: "/editor/a11y-review", state: "loaded-review" },
    { route: "/editor/a11y-review", state: "preview" },
    { route: "/editor/a11y-review", state: "history" },
    { route: "/r/a11y-result", state: "saved-result" },
    { route: "/r/missing", state: "missing-result" },
    { route: "/graph/a11yproject", state: "graph" },
    { route: "/graph/missing", state: "missing-graph" },
  ];
  for (const width of [1440, 390]) for (const theme of ["light", "dark"]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 }, colorScheme: theme as "light" | "dark", reducedMotion: "reduce" });
    for (const scenario of cases) {
      const page = await context.newPage();
      await seed(page, theme);
      await page.goto(scenario.route);
      if (scenario.route.startsWith("/editor/")) await page.waitForURL(/\/editor\?id=/);
      if (scenario.state === "speed-menu") await page.getByRole("button", { name: /^Research speed mode/ }).click();
      if (scenario.state === "research-complete") {
        await page.getByRole("textbox").first().fill("Accessible research interfaces");
        await page.getByRole("textbox").first().press("Enter");
        await expect(page.getByText("Research Complete", { exact: false }).first()).toBeVisible();
      }
      if (scenario.state === "preview") await page.getByRole("button", { name: "Preview", exact: true }).click();
      if (scenario.state === "history") await page.getByRole("button", { name: "Toggle Sidebar", exact: true }).first().click();
      // Wait for hydration, dynamic imports, and Framer Motion's final styles.
      await page.waitForTimeout(1200);
      const audit = await new AxeBuilder({ page }).withTags(tags).analyze();
      const violations = audit.violations.map(v => ({
        rule: v.id, impact: v.impact, page: scenario.route, node_count: v.nodes.length,
        description: v.description, help: v.help, help_url: v.helpUrl,
        nodes: v.nodes.map(n => ({ target: n.target, html: n.html, failure_summary: n.failureSummary })),
      }));
      scans.push({ page: scenario.route, resolved_url: page.url(), state: scenario.state, width, theme,
        violations, incomplete: audit.incomplete, axe_version: audit.testEngine.version });
      if (violations.length) failures.push(`${width}px ${theme} ${scenario.route} (${scenario.state}): ${violations.map(v => `${v.rule}=${v.node_count}`).join(", ")}`);
      await page.close();
    }
    await context.close();
  }
  const all = scans.flatMap(s => s.violations as Array<{ rule: string; node_count: number }>);
  const by_rule: Record<string, { violations: number; affected_nodes: number }> = {};
  for (const v of all) {
    const count = by_rule[v.rule] ??= { violations: 0, affected_nodes: 0 };
    count.violations++; count.affected_nodes += v.node_count;
  }
  const report = { generated_at: new Date().toISOString(), tags, widths: [1440, 390], themes: ["light", "dark"],
    totals: { scans: scans.length, violations: all.length, affected_nodes: all.reduce((sum, v) => sum + v.node_count, 0) }, by_rule, scans };
  await testInfo.attach("accessibility", { body: JSON.stringify(report, null, 2), contentType: "application/json" });
  if (phase) {
    const destination = resolve("../a11y", `${phase}.json`);
    await mkdir(resolve("../a11y"), { recursive: true });
    // Baseline is immutable: never silently replace the evidence from the original source.
    await writeFile(destination, JSON.stringify(report, null, 2) + "\n", { flag: phase === "baseline" ? "wx" : "w" });
  }
  expect(phase === "baseline" ? [] : failures, failures.join("\n")).toEqual([]);
});

test("keyboard navigation preserves focus and exposes citation and review controls", async ({ page }) => {
  test.skip(process.env.A11Y_PHASE === "baseline", "Baseline records the original source before keyboard fixes");
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await seed(page, "light");
    await page.goto("/");
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("main#main-content")).toBeFocused();
    await expect(page.locator("main")).toHaveCount(1);
    const speed = page.getByRole("button", { name: /^Research speed mode/ });
    await speed.focus();
    await page.keyboard.press("ArrowDown");
    await expect(page.getByRole("menuitemradio", { name: /Fast/ })).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(speed).toBeFocused();
    await expect(speed).toHaveAccessibleName("Research speed mode: Medium");
    await page.keyboard.press("Space");
    await page.keyboard.press("Escape");
    await expect(speed).toBeFocused();
    await expect(speed).toHaveAttribute("aria-expanded", "false");
    await page.goto("/editor/a11y-review");
    await page.waitForURL(/\/editor\?id=/);
    await page.getByRole("button", { name: "Toggle Sidebar", exact: true }).first().click();
    const reviewButton = page.getByRole("button", { name: "Accessible research interfaces", exact: true });
    await expect(reviewButton).toBeVisible();
    await reviewButton.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "Compile", exact: true })).toBeEnabled();
    await page.goto("/graph/a11yproject");
    const citations = page.locator("summary");
    await citations.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "Accessible research interfaces", exact: true })).toBeVisible();
  }
});
