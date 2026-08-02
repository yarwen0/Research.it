import { describe, it, expect } from "vitest";
import {
  transformPaper,
  transformPapers,
  isBackendPaper,
  needsTransformation,
  ensureFrontendFormat,
  type BackendPaper,
} from "./paper-transform";

function makeBackendPaper(overrides: Partial<BackendPaper> = {}): BackendPaper {
  return {
    paper_id: "p1",
    title: "A Great Paper",
    authors: ["Alice", "Bob", "Carol"],
    published: "2024",
    pdf_url: "http://example.com/p1.pdf",
    references: [],
    topic: "machine learning",
    extraction: {
      problem: "hard problem",
      methods: [],
      datasets: [],
      assumptions_explicit: [],
      assumptions_implicit: [],
      limitations_explicit: [],
      limitations_implied: [],
      future_work: [],
    },
    normalized: {
      problem: "normalized problem",
      methods: [],
      datasets: [],
      assumptions_explicit: [],
      assumptions_implicit: [],
      limitations_explicit: [],
      limitations_implied: [],
      future_work: [],
    },
    ...overrides,
  };
}

describe("transformPaper", () => {
  it("maps title, first two authors + topic as keywords, and problem as abstract", () => {
    const result = transformPaper(makeBackendPaper());
    expect(result.title).toBe("A Great Paper");
    expect(result.keywords).toEqual(["Alice", "Bob", "machine learning"]);
    expect(result.abstract).toBe("hard problem");
    expect(result._original).toBeDefined();
  });

  it("falls back to 'Untitled Paper' when title is empty", () => {
    expect(transformPaper(makeBackendPaper({ title: "" })).title).toBe("Untitled Paper");
  });

  it("falls back to normalized problem, then to a default, for the abstract", () => {
    const extraction = { ...makeBackendPaper().extraction, problem: "" };
    expect(transformPaper(makeBackendPaper({ extraction })).abstract).toBe("normalized problem");

    const normalized = { ...makeBackendPaper().normalized, problem: "" };
    expect(
      transformPaper(makeBackendPaper({ extraction, normalized })).abstract,
    ).toBe("No abstract available");
  });

  it("filters out empty keyword slots when authors/topic are missing", () => {
    const result = transformPaper(
      makeBackendPaper({ authors: [], topic: "" }),
    );
    expect(result.keywords).toEqual([]);
  });

  it("truncates long topics to 50 characters in keywords", () => {
    const longTopic = "a".repeat(60);
    const result = transformPaper(makeBackendPaper({ authors: [], topic: longTopic }));
    expect(result.keywords).toEqual([longTopic.substring(0, 50)]);
  });
});

describe("transformPapers", () => {
  it("transforms every paper in the array", () => {
    const out = transformPapers([makeBackendPaper(), makeBackendPaper({ title: "Second" })]);
    expect(out.map((p) => p.title)).toEqual(["A Great Paper", "Second"]);
  });
});

describe("isBackendPaper", () => {
  it("recognises backend papers by paper_id", () => {
    expect(isBackendPaper({ paper_id: "x" })).toBe(true);
  });

  it("rejects null, non-objects, and objects without paper_id", () => {
    expect(isBackendPaper(null)).toBe(false);
    expect(isBackendPaper("string")).toBe(false);
    expect(isBackendPaper({ title: "no id" })).toBe(false);
  });
});

describe("needsTransformation", () => {
  it("is false for an empty array", () => {
    expect(needsTransformation([])).toBe(false);
  });

  it("is true when the first item is a backend paper", () => {
    expect(needsTransformation([{ paper_id: "x" }])).toBe(true);
  });

  it("is false when the first item is already frontend-shaped", () => {
    expect(needsTransformation([{ title: "x", keywords: [], abstract: "" }])).toBe(false);
  });
});

describe("ensureFrontendFormat", () => {
  it("transforms backend papers", () => {
    const out = ensureFrontendFormat([makeBackendPaper()]);
    expect(out[0].abstract).toBe("hard problem");
  });

  it("returns already-frontend papers unchanged", () => {
    const frontend = [{ title: "x", keywords: ["k"], abstract: "a" }];
    expect(ensureFrontendFormat(frontend)).toBe(frontend);
  });
});
