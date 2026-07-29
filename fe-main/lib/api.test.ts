import { describe, it, expect, vi, afterEach } from "vitest";
import { APIError, fetchGraph } from "./api";

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
