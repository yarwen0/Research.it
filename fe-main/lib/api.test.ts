import { describe, it, expect, vi, afterEach } from "vitest";
import {
  APIError,
  KEEPALIVE_INTERVAL_MS,
  compileLatex,
  errorFromResponse,
  fetchGraph,
  keepApiAwakeDuring,
  wakeApi,
} from "./api";

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
    const error = await errorFromResponse(new Response("Forbidden", { status: 403 }), "Graph fetch failed");
    expect(error.message).toBe("Graph fetch failed: HTTP 403");
  });

  it("explains a gateway error from an idle host", async () => {
    const error = await errorFromResponse(new Response("<html>Bad gateway</html>", { status: 502 }), "Graph fetch failed");
    expect(error.message).toMatch(/^Graph fetch failed: the API did not respond \(HTTP 502\)\. .*starting up/);
  });

  it("still quotes the API's own 503", async () => {
    const error = await errorFromResponse(json({ detail: "No TeX toolchain is installed" }, 503), "Compilation failed");
    expect(error.message).toBe("Compilation failed: No TeX toolchain is installed");
  });

  it("quotes the request id of a server error so its logs can be found", async () => {
    const response = new Response(JSON.stringify({ detail: "Failed to retrieve graph" }), {
      status: 500,
      headers: { "X-Request-ID": "3f2a9c" },
    });
    const error = await errorFromResponse(response, "Graph fetch failed");
    expect(error.message).toBe("Graph fetch failed: Failed to retrieve graph (request 3f2a9c)");
  });

  it("leaves the request id off a client error", async () => {
    const response = new Response(JSON.stringify({ detail: "Review not found" }), {
      status: 404,
      headers: { "X-Request-ID": "3f2a9c" },
    });
    const error = await errorFromResponse(response, "Review fetch failed");
    expect(error.message).toBe("Review fetch failed: Review not found");
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

describe("an unreachable API", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("says where the request was going", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(compileLatex("\\documentclass{article}")).rejects.toMatchObject({
      name: "APIError",
      message: expect.stringMatching(/^Could not reach the API at http.* \(Failed to fetch\)\. .*starting up/),
    });
  });
});

describe("wakeApi", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("pings the health endpoint", () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    wakeApi();

    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/health$/));
  });

  it("swallows a failure, leaving the real request to report it", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    expect(() => wakeApi()).not.toThrow();
    // Let the rejection settle; an unhandled one would fail the run.
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
});

describe("keepApiAwakeDuring", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("pings inside Render's 15-minute idle window until the work settles", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    expect(KEEPALIVE_INTERVAL_MS).toBeLessThan(15 * 60 * 1000);

    let finish!: (value: string) => void;
    const work = keepApiAwakeDuring(new Promise<string>((resolve) => (finish = resolve)));

    await vi.advanceTimersByTimeAsync(20 * 60 * 1000);
    expect(fetchMock).toHaveBeenCalledTimes(5);

    finish("done");
    await expect(work).resolves.toBe("done");

    await vi.advanceTimersByTimeAsync(20 * 60 * 1000);
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });

  it("stops pinging when the work fails", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    await expect(keepApiAwakeDuring(Promise.reject(new Error("dropped")))).rejects.toThrow("dropped");
    await vi.advanceTimersByTimeAsync(20 * 60 * 1000);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
