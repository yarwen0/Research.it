import { StreamHandler, StreamHandlerCallbacks } from "./stream_handler";

/**
 * API Configuration
 */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

/**
 * Research request payload
 */
export interface ResearchRequest {
  user_prompt: string;
  num_topics: number;
  papers_per_topic: number;
}

/**
 * API Error class
 */
export class APIError extends Error {
  constructor(
    message: string,
    public statusCode?: number,
    public response?: Response
  ) {
    super(message);
    this.name = "APIError";
  }
}

/**
 * Submit a research request to the backend
 * Returns a StreamHandler that processes the SSE response
 * 
 * @param text - The text to research
 * @param numTopics - Number of topics to analyze
 * @param papersPerTopic - Number of papers per topic
 * @param callbacks - Callbacks for handling stream events
 * @returns StreamHandler instance
 * 
 * @example
 * const handler = await submitResearch("plastic recycling", 2, 2, {
 *   onUpdate: (update) => console.log(update.message),
 *   onProgress: (update) => console.log("Progress:", update.result),
 *   onCompleted: (update) => console.log("Done:", update.result),
 *   onError: (error) => console.error("Error:", error),
 * });
 */
export async function submitResearch(
  text: string,
  numTopics: number = 2,
  papersPerTopic: number = 2,
  callbacks?: StreamHandlerCallbacks
): Promise<StreamHandler> {
  const url = `${API_BASE_URL}/api/research`;
  
  const payload: ResearchRequest = { 
    user_prompt: text,
    num_topics: numTopics,
    papers_per_topic: papersPerTopic
  };

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new APIError(
        `API request failed: ${response.statusText}`,
        response.status,
        response
      );
    }

    // Check if response is SSE
    const contentType = response.headers.get("content-type");
    if (!contentType?.includes("text/event-stream")) {
      throw new APIError(
        `Expected text/event-stream but got ${contentType}`,
        response.status,
        response
      );
    }

    // Create stream handler and start processing
    const handler = new StreamHandler(callbacks);
    
    // Start processing in background (don't await)
    handler.processStream(response).catch((error) => {
      callbacks?.onError?.(error.message);
    });

    return handler;
  } catch (error) {
    if (error instanceof APIError) {
      throw error;
    }
    
    const errorMessage = error instanceof Error ? error.message : "Unknown error";
    throw new APIError(`Network error: ${errorMessage}`);
  }
}

/**
 * Helper function to collect all updates from a research request
 * Useful for testing or when you need all results at once
 * 
 * @param text - The text to research
 * @param numTopics - Number of topics to analyze
 * @param papersPerTopic - Number of papers per topic
 * @returns Promise that resolves with all updates
 */
export async function submitResearchAndCollect(
  text: string,
  numTopics: number = 2,
  papersPerTopic: number = 2
): Promise<Array<any>> {
  const updates: Array<any> = [];
  
  return new Promise((resolve, reject) => {
    submitResearch(text, numTopics, papersPerTopic, {
      onUpdate: (update: any) => updates.push(update),
      onCompleted: () => resolve(updates),
      onError: (error: any) => reject(new Error(error)),
    }).catch(reject);
  });
}

/**
 * Fetch the citation graph for a completed research session
 */
export async function fetchGraph(projectId: string): Promise<{ nodes: any[]; edges: any[] }> {
  const url = `${API_BASE_URL}/api/graph/${projectId}/`;
  const response = await fetch(url);
  if (!response.ok) throw new APIError(`Graph fetch failed: ${response.statusText}`, response.status);
  const data = await response.json();
  return data.graph_data;
}

export interface CreateReviewRequest {
  saved_filepath: string;
  paper_index: number;
  paper_info: {
    title: string;
    keywords: string[];
    abstract: string;
  };
}

/**
 * Submit a literature review generation request to the backend.
 * Returns a StreamHandler that processes the SSE response.
 */
export async function submitCreateReview(
  request: CreateReviewRequest,
  callbacks: StreamHandlerCallbacks
): Promise<StreamHandler> {
  const url = `${API_BASE_URL}/api/create_review`;

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new APIError(
        `Failed to start review generation: ${response.statusText}`,
        response.status,
        response
      );
    }

    const streamHandler = new StreamHandler(callbacks);
    await streamHandler.processStream(response);
    return streamHandler;
  } catch (error) {
    if (error instanceof APIError) {
      throw error;
    }

    const errorMessage = error instanceof Error ? error.message : "Unknown error";
    throw new APIError(`Network error: ${errorMessage}`);
  }
}

/**
 * Compile LaTeX content to PDF
 * Sends LaTeX content to the backend and returns a PDF blob
 * 
 * @param latexContent - The LaTeX content to compile
 * @returns Promise that resolves with a Blob containing the PDF
 * 
 * @example
 * const pdf = await compileLatex("\\documentclass{article}...");
 * const url = URL.createObjectURL(pdf);
 */
export async function compileLatex(latexContent: string): Promise<Blob> {
  const url = `${API_BASE_URL}/api/latex/compile`;
  
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        latex_text: latexContent,
      }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: response.statusText }));
      throw new APIError(
        errorData.error || `Compilation failed: ${response.statusText}`,
        response.status,
        response
      );
    }

    return await response.blob();
  } catch (error) {
    if (error instanceof APIError) {
      throw error;
    }
    
    const errorMessage = error instanceof Error ? error.message : "Unknown error";
    throw new APIError(`Network error: ${errorMessage}`);
  }
}
