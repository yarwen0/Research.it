import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = new URL("../../a11y/", import.meta.url);
const before = JSON.parse(await readFile(new URL("baseline.json", root), "utf8"));
const after = JSON.parse(await readFile(new URL("after.json", root), "utf8"));
const rules = [...new Set([...Object.keys(before.by_rule), ...Object.keys(after.by_rule)])].sort();
const rows = rules.map(rule => {
  const b = before.by_rule[rule] ?? { violations: 0, affected_nodes: 0 };
  const a = after.by_rule[rule] ?? { violations: 0, affected_nodes: 0 };
  return `| ${rule} | ${b.violations} | ${b.affected_nodes} | ${a.violations} | ${a.affected_nodes} |`;
});
const incompletes = after.scans.reduce((sum, scan) => sum + scan.incomplete.length, 0);
const text = `# Research.it accessibility pass

Before: **${before.totals.violations} violations affecting ${before.totals.affected_nodes} nodes** across ${before.totals.scans} scans.

After: **${after.totals.violations} violations affecting ${after.totals.affected_nodes} nodes** across ${after.totals.scans} scans.

These values and the table are generated directly from baseline.json and after.json by \`node fe-main/scripts/a11y-report.mjs\`. A violation means one rule finding in a page/state/viewport/theme scan; affected nodes count appearances across scans rather than unique elements across the application. The original baseline is kept unchanged.

| Rule | Before violations | Before affected nodes | After violations | After affected nodes |
|---|---|---|---|---|
${rows.join("\n")}
| Total | ${before.totals.violations} | ${before.totals.affected_nodes} | ${after.totals.violations} | ${after.totals.affected_nodes} |

## Scope and method

Playwright Chromium and @axe-core/playwright scan the full document with tags ${after.tags.join(", ")}. Viewport widths are ${after.widths.join(" and ")} pixels, in ${after.themes.join(" and ")} themes. No axe rules are disabled, no document regions are excluded, and no violations are suppressed.

All app-router page routes are covered: \`/\`, \`/editor\`, \`/editor/[id]\`, \`/r/[id]\`, and \`/graph/[project_id]\`. The ID editor redirects to the real editor and its loaded state is scanned. Scenarios include the speed menu, completed research, saved and missing results, editing, PDF preview placeholder, open review history, and loaded and missing citation graphs. Fixtures provide representative local-storage history and streamed research results. A local HTTP fixture serves the graph requested by the Next server; the browser-level research stub follows the existing e2e approach. Scans exercise fixture data, not every possible research result or dataset-driven chart.

## Changes

- The speed button includes its visible selected mode in its accessible name. Its menu exposes selection state, supports arrow keys, Home/End, Enter and Escape, and returns focus to its trigger. The global printable-key handler was removed so it no longer steals typing from other controls.
- Darker menu descriptions, research titles, preview placeholders, and theme-aware history timestamps resolve the measured contrast failures.
- The sidebar wrapper no longer produces nested main elements. Pages expose a focusable main destination, the editor has a heading, and a visible-on-focus skip link bypasses navigation. Keyboard focus has a visible outline in both themes.
- Review selection and research deletion use independently focusable buttons. Selecting a review or result closes the mobile dialog; the dialog also exposes its close button.
- The source editor requests Monaco screen-reader support, has an explicit accessible name, and allows Tab to leave the editor. The dedicated graph offers a native disclosure with citation relationships and keyboard-selectable entries alongside its visual rendering.

## Verification

\`pnpm test:a11y\` passes the route scans and browser keyboard checks. The keyboard check exercises the skip link, main focus, speed menu selection and Escape, review selection, mobile dialog dismissal, and graph list disclosure at both viewport widths. Frontend typecheck, lint, unit tests, the existing e2e suite, and the production build also pass. Lint retains existing React/compiler warnings; this pass adds no accessibility rule suppressions.

The existing GitHub Actions e2e job now runs \`pnpm test:a11y\` after the regression suite. Scan output is attached to Playwright results. To refresh after measurements, run \`A11Y_PHASE=after pnpm --dir fe-main test:a11y\`, then regenerate this report. The baseline command uses exclusive file creation to prevent accidentally replacing the original evidence.

## Manual keyboard and screen-reader notes

Browser automation verifies the keyboard interactions described above; a complete manual keyboard traversal and assistive-technology session have **not** been performed. Verify VoiceOver/Safari and another screen reader with the real editor loaded, mobile dialog announcements and focus restoration, long result sets, bibliography dialogs, error/status announcements, zoom/reflow, and chart alternatives. The PDF viewer and generated PDF also need separate review.

Axe cannot establish that names and alt text are meaningful, reading and focus order are sensible for every result, graph relationships and charts convey equivalent meaning, live updates are understandable, or all third-party editor/PDF functionality is usable. Monaco loads external runtime assets; a scan alone cannot establish that runtime's accessibility. Passing the automated scan is not a claim of complete WCAG conformance.

The raw after scans retain ${incompletes} incomplete rule findings that require human review, including any contrast checks axe could not resolve automatically. Review their node details in after.json before making a conformance claim.
`;
await writeFile(new URL("REPORT.md", root), text);
console.log(JSON.stringify({ report: fileURLToPath(new URL("REPORT.md", root)), before: before.totals, after: after.totals }, null, 2));
