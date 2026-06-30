/**
 * Status types matching backend SSEUpdate
 */
export enum StatusType {
  PROCESSING = "processing",
  SUCCESS = "success",
  ERROR = "error",
  PROGRESS = "progress",
  COMPLETED = "completed",
}

/**
 * SSE Update structure matching backend model
 */
export interface SSEUpdate {
  status: StatusType;
  message: string;
  result?: Record<string, any> | null;
}

/**
 * Callbacks for different SSE events
 */
export interface StreamHandlerCallbacks {
  onUpdate?: (update: SSEUpdate) => void;
  onProgress?: (update: SSEUpdate) => void;
  onSuccess?: (update: SSEUpdate) => void;
  onCompleted?: (update: SSEUpdate) => void;
  onError?: (error: string, update?: SSEUpdate) => void;
  onEnd?: () => void;
}

/**
 * Stream handler for Server-Sent Events
 * Processes SSE data from the backend research API
 */
export class StreamHandler {
  private reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  private decoder = new TextDecoder();
  private buffer = "";

  constructor(private callbacks: StreamHandlerCallbacks = {}) {}

  /**
   * Start processing a stream from a Response object
   */
  async processStream(response: Response): Promise<void> {
    if (!response.body) {
      throw new Error("Response body is null");
    }

    this.reader = response.body.getReader();
    
    try {
      while (true) {
        const { done, value } = await this.reader.read();

        if (done) {
          // Process any remaining data in buffer
          if (this.buffer.trim()) {
            this.processBuffer();
          }
          this.callbacks.onEnd?.();
          break;
        }

        // Decode chunk and add to buffer
        const chunk = this.decoder.decode(value, { stream: true });
        this.buffer += chunk;

        // Process complete messages in buffer
        this.processBuffer();
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Unknown error";
      this.callbacks.onError?.(errorMessage);
      throw error;
    } finally {
      this.reader?.releaseLock();
      this.reader = null;
    }
  }

  /**
   * Process buffered data and extract complete SSE messages
   */
  private processBuffer(): void {
    const lines = this.buffer.split("\n");
    
    // Keep the last incomplete line in the buffer
    this.buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = line.slice(6).trim();
        if (data) {
          this.handleMessage(data);
        }
      }
    }
  }

  /**
   * Parse and handle a single SSE message
   */
  private handleMessage(data: string): void {
    try {
      const update: SSEUpdate = JSON.parse(data);
      
      // Call generic update callback
      this.callbacks.onUpdate?.(update);

      // Call specific callbacks based on status
      switch (update.status) {
        case StatusType.PROCESSING:
          // Just a processing update, no special handling needed
          break;
        case StatusType.PROGRESS:
          this.callbacks.onProgress?.(update);
          break;
        case StatusType.SUCCESS:
          this.callbacks.onSuccess?.(update);
          // Also trigger onCompleted for success status (final result)
          this.callbacks.onCompleted?.(update);
          break;
        case StatusType.COMPLETED:
          this.callbacks.onCompleted?.(update);
          break;
        case StatusType.ERROR:
          this.callbacks.onError?.(update.message, update);
          break;
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Failed to parse SSE message";
      this.callbacks.onError?.(`Parse error: ${errorMessage}`);
    }
  }

  /**
   * Cancel the stream
   */
  cancel(): void {
    if (this.reader) {
      this.reader.cancel();
      this.reader = null;
    }
  }
}
