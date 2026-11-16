import { describe, it, expect } from "vitest";
import { siteUrl } from "./site-url";

describe("siteUrl", () => {
  it("prefers the configured site URL", () => {
    expect(
      siteUrl({
        NEXT_PUBLIC_SITE_URL: "https://researchit.example.com",
        VERCEL_PROJECT_PRODUCTION_URL: "research-it.vercel.app",
      }),
    ).toBe("https://researchit.example.com");
  });

  it("uses Vercel's production domain when none is configured", () => {
    expect(siteUrl({ VERCEL_PROJECT_PRODUCTION_URL: "research-it.vercel.app" })).toBe(
      "https://research-it.vercel.app",
    );
  });

  it("falls back to the local dev server", () => {
    expect(siteUrl({})).toBe("http://localhost:3000");
  });
});
