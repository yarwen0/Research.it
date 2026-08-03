import { describe, it, expect, vi, type Mock } from "vitest";
import { StreamHandler, StreamHandlerCallbacks } from "./stream_handler";

/** Build a Response whose body streams the given string chunks as SSE bytes. */
function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
  return new Response(stream);
}

/**
 * Every callback, as a mock. Annotating with `Required<StreamHandlerCallbacks>`
 * alone kept the completeness check but erased the mock types, so `.mock.calls`
 * was not reachable from a test.
 */
type MockedCallbacks = {
  [K in keyof Required<StreamHandlerCallbacks>]: Mock<Required<StreamHandlerCallbacks>[K]>;
};

function spies(): MockedCallbacks {
  return {
    onUpdate: vi.fn(),
    onProgress: vi.fn(),
    onSuccess: vi.fn(),
    onCompleted: vi.fn(),
    onError: vi.fn(),
    onEnd: vi.fn(),
  };
}

describe("StreamHandler.processStream", () => {
  it("dispatches update, progress, completed and end callbacks", async () => {
    const cb = spies();
    await new StreamHandler(cb).processStream(
      sseResponse([
        'data: {"status":"processing","message":"start"}\n\n',
        'data: {"status":"progress","message":"p","result":{"n":1}}\n\n',
        'data: {"status":"completed","message":"done","result":{"ok":true}}\n\n',
      ]),
    );

    expect(cb.onUpdate).toHaveBeenCalledTimes(3);
    expect(cb.onProgress).toHaveBeenCalledTimes(1);
    expect(cb.onProgress).toHaveBeenCalledWith(
      expect.objectContaining({ message: "p", result: { n: 1 } }),
    );
    expect(cb.onCompleted).toHaveBeenCalledTimes(1);
    expect(cb.onEnd).toHaveBeenCalledTimes(1);
  });

  it("treats success as both success and completed", async () => {
    const cb = spies();
    await new StreamHandler(cb).processStream(
      sseResponse(['data: {"status":"success","message":"s"}\n\n']),
    );
    expect(cb.onSuccess).toHaveBeenCalledTimes(1);
    expect(cb.onCompleted).toHaveBeenCalledTimes(1);
  });

  it("reassembles a message split across chunk boundaries", async () => {
    const cb = spies();
    const message = 'data: {"status":"progress","message":"hello","result":{"x":5}}\n\n';
    await new StreamHandler(cb).processStream(
      sseResponse([message.slice(0, 20), message.slice(20)]),
    );
    expect(cb.onProgress).toHaveBeenCalledTimes(1);
    expect(cb.onProgress).toHaveBeenCalledWith(
      expect.objectContaining({ message: "hello", result: { x: 5 } }),
    );
  });

  it("routes error status to onError with the update", async () => {
    const cb = spies();
    await new StreamHandler(cb).processStream(
      sseResponse(['data: {"status":"error","message":"boom"}\n\n']),
    );
    expect(cb.onError).toHaveBeenCalledWith("boom", expect.objectContaining({ message: "boom" }));
  });

  it("reports a parse error on malformed JSON", async () => {
    const cb = spies();
    await new StreamHandler(cb).processStream(sseResponse(["data: not-json\n\n"]));
    expect(cb.onError).toHaveBeenCalledTimes(1);
    expect(cb.onError.mock.calls[0][0]).toMatch(/^Parse error:/);
  });

  it("ignores non-data lines", async () => {
    const cb = spies();
    await new StreamHandler(cb).processStream(
      sseResponse(["event: ping\n\n", 'data: {"status":"processing","message":"ok"}\n\n']),
    );
    expect(cb.onUpdate).toHaveBeenCalledTimes(1);
  });

  it("rejects a response with a null body", async () => {
    const cb = spies();
    await expect(
      new StreamHandler(cb).processStream(new Response(null, { status: 200 })),
    ).rejects.toThrow("Response body is null");
  });
});
