import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Unit tests only. Vitest's default glob also matches *.spec.ts, which
    // would sweep up the Playwright suite in e2e/ and fail on its imports.
    include: ["lib/**/*.test.ts", "app/**/*.test.ts", "app/**/*.test.tsx"],
    exclude: ["node_modules", ".next", "e2e"],
  },
});
