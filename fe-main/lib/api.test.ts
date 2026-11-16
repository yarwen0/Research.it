import { describe, it, expect, vi, afterEach } from "vitest";
import { APIError, compileLatex, errorFromResponse, fetchGraph } from "./api";

describe("APIError", () => {
  it("sets name and statusCode", () => {
    const error = new APIError("Graph fetch failed", 404);
    expect(error.name).toBe("APIError");
    expect(error.message).toBe("Graph fetch failed");
    expect(error.statusCode).toBe(404);
  });
});

describe("fetchGraph", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("throws APIError when the response is not ok", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: "Not Found",
      }),
    );

    await expect(fetchGraph("missing-project")).rejects.toMatchObject({
      name: "APIError",
      statusCode: 404,
    });
  });

  it("returns graph_data from a successful response", async () => {
    const graphData = { nodes: [{ data: { id: "n1" } }], edges: [] };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ graph_data: graphData }),
      }),
    );

    await expect(fetchGraph("project-1")).resolves.toEqual(graphData);
  });
});

describe("errorFromResponse", () => {
  const json = (body: unknown, status: number, statusText = "") =>
    new Response(JSON.stringify(body), {
      status,
      statusText,
      headers: { "Content-Type": "application/json" },
    });

  it("quotes the backend's detail", async () => {
    const error = await errorFromResponse(
      json({ detail: "Rate limit exceeded: 5 per 1 hour." }, 429),
      "Research request failed",
    );
    expect(error.message).toBe("Research request failed: Rate limit exceeded: 5 per 1 hour.");
    expect(error.statusCode).toBe(429);
  });

  it("joins FastAPI's validation errors", async () => {
    const error = await errorFromResponse(
      json(
        {
          detail: [
            { loc: ["body", "user_prompt"], msg: "String should have at least 1 character" },
            { loc: ["body", "num_topics"], msg: "Input should be greater than 0" },
          ],
        },
        422,
      ),
      "Research request failed",
    );
    expect(error.message).toBe(
      "Research request failed: String should have at least 1 character; Input should be greater than 0",
    );
  });

  it("falls back to the status code when HTTP/2 leaves statusText empty", async () => {
    const error = await errorFromResponse(new Response("<html>Bad gateway</html>", { status: 502 }), "Graph fetch failed");
    expect(error.message).toBe("Graph fetch failed: HTTP 502");
  });

  it("uses statusText when there is no detail to quote", async () => {
    const error = await errorFromResponse(json({}, 404, "Not Found"), "Job fetch failed");
    expect(error.message).toBe("Job fetch failed: Not Found");
  });
});

describe("compileLatex", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("reports why the document did not compile", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Undefined control sequence \\citep" }), { status: 400 }),
      ),
    );

    await expect(compileLatex("\\documentclass{article}")).rejects.toMatchObject({
      name: "APIError",
      statusCode: 400,
      message: "Compilation failed: Undefined control sequence \\citep",
    });
  });
});
