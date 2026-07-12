/**
 * Paper transformation utilities
 * Transforms backend paper format to frontend display format
 */

/**
 * Backend paper format (from arXiv research API)
 */
export interface BackendPaper {
  paper_id: string;
  title: string;
  authors: string[];
  published: string;
  pdf_url: string;
  references: any[];
  topic: string;
  extraction: {
    problem: string;
    methods: string[];
    datasets: string[];
    assumptions_explicit: string[];
    assumptions_implicit: string[];
    limitations_explicit: string[];
    limitations_implied: string[];
    future_work: string[];
  };
  normalized: {
    problem: string;
    methods: [string, string][];
    datasets: [string, string][];
    assumptions_explicit: [string, string][];
    assumptions_implicit: [string, string][];
    limitations_explicit: [string, string][];
    limitations_implied: [string, string][];
    future_work: [string, string][];
  };
}

/**
 * Frontend paper format (for UI display)
 */
export interface FrontendPaper {
  title: string;
  keywords: string[];
  abstract: string;
  _original?: BackendPaper; // Keep original for detailed views
}

/**
 * Transform a single backend paper to frontend format
 */
export function transformPaper(paper: BackendPaper): FrontendPaper {
  return {
    title: paper.title || 'Untitled Paper',
    keywords: [
      ...(paper.authors || []).slice(0, 2), // Add first 2 authors as keywords
      paper.topic?.substring(0, 50) || '', // Add shortened topic
    ].filter(Boolean),
    abstract: paper.extraction?.problem || paper.normalized?.problem || 'No abstract available',
    _original: paper,
  };
}

/**
 * Transform an array of backend papers to frontend format
 */
export function transformPapers(papers: BackendPaper[]): FrontendPaper[] {
  return papers.map(transformPaper);
}

/**
 * Check if a paper is in backend format
 */
export function isBackendPaper(paper: any): paper is BackendPaper {
  return !!paper && typeof paper === 'object' && 'paper_id' in paper;
}

/**
 * Check if papers need transformation
 */
export function needsTransformation(papers: any[]): boolean {
  return papers.length > 0 && isBackendPaper(papers[0]);
}

/**
 * Transform papers if needed, otherwise return as-is
 */
export function ensureFrontendFormat(papers: any[]): FrontendPaper[] {
  if (needsTransformation(papers)) {
    return transformPapers(papers as BackendPaper[]);
  }
  return papers as FrontendPaper[];
}
