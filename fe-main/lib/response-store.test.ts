import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { formatTimestamp, formatDuration } from "./response-store";

describe("formatTimestamp", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-26T15:00:00"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows time for timestamps within 24 hours", () => {
    const twoHoursAgo = new Date("2026-07-26T13:00:00").getTime();
    expect(formatTimestamp(twoHoursAgo)).toMatch(/\d{1,2}:\d{2}/);
  });

  it("shows Yesterday for timestamps 24-48 hours ago", () => {
    const yesterday = new Date("2026-07-25T14:00:00").getTime();
    expect(formatTimestamp(yesterday)).toBe("Yesterday");
  });

  it("shows weekday for timestamps within a week", () => {
    const threeDaysAgo = new Date("2026-07-23T15:00:00").getTime();
    expect(formatTimestamp(threeDaysAgo)).toMatch(/^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)$/);
  });
});

describe("formatDuration", () => {
  it("formats seconds only", () => {
    expect(formatDuration(45_000)).toBe("45s");
  });

  it("formats minutes and seconds", () => {
    expect(formatDuration(125_000)).toBe("2m 5s");
  });

  it("formats minutes without trailing zero seconds", () => {
    expect(formatDuration(120_000)).toBe("2m");
  });

  it("formats hours and minutes", () => {
    expect(formatDuration(3_900_000)).toBe("1h 5m");
  });
});
