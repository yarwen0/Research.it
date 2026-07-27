/**
 * Response Store - Persistent storage for research responses using localStorage
 */

export interface ResearchResponse {
  id: string;
  prompt: string;
  timestamp: number;
  // Timing information
  startTime?: number; // When research started
  endTime?: number; // When research completed
  duration?: number; // Total duration in milliseconds
  // Backend response data (raw from API)
  user_prompt: string;
  topics: string[]; // Generated research topics
  total_papers: number;
  processed_papers: any[]; // Raw backend papers with paper_id, extraction, normalized, etc.
  suggested_papers: any[]; // Papers in frontend format (title, keywords, abstract) - ready for display
  saved_filepath?: string;
  project_id?: string;
  trends: any; // Research metrics and analysis data
  datasets?: any; // Dataset information from backend
  // Research progress details (all SSE updates)
  progressUpdates?: any[];
  // Legacy/UI fields
  papers?: any[]; // Fallback field for backward compatibility
  metrics?: any; // Alias for trends
  graphData?: any; // Full result object
  speedMode: 'fast' | 'medium' | 'slow';
}

const STORAGE_KEY = 'research_responses';
const MAX_RESPONSES = 50; // Limit stored responses

/**
 * Get all stored responses from localStorage
 */
export function getStoredResponses(): ResearchResponse[] {
  if (typeof window === 'undefined') return [];
  
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) return [];
    return JSON.parse(stored);
  } catch (error) {
    console.error('Error reading from localStorage:', error);
    return [];
  }
}

/**
 * Save a new response to localStorage
 */
export function saveResponse(response: Omit<ResearchResponse, 'id' | 'timestamp'>): ResearchResponse {
  const newResponse: ResearchResponse = {
    ...response,
    id: generateId(),
    timestamp: Date.now(),
  };

  try {
    const responses = getStoredResponses();
    
    // Add new response at the beginning
    const updatedResponses = [newResponse, ...responses];
    
    // Limit the number of stored responses
    const limitedResponses = updatedResponses.slice(0, MAX_RESPONSES);
    
    localStorage.setItem(STORAGE_KEY, JSON.stringify(limitedResponses));
    return newResponse;
  } catch (error) {
    console.error('Error saving to localStorage:', error);
    return newResponse;
  }
}

/**
 * Get a specific response by ID
 */
export function getResponseById(id: string): ResearchResponse | null {
  const responses = getStoredResponses();
  return responses.find(r => r.id === id) || null;
}

/**
 * Delete a response by ID
 */
export function deleteResponse(id: string): void {
  try {
    const responses = getStoredResponses();
    const filtered = responses.filter(r => r.id !== id);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(filtered));
  } catch (error) {
    console.error('Error deleting from localStorage:', error);
  }
}

/**
 * Clear all stored responses
 */
export function clearAllResponses(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch (error) {
    console.error('Error clearing localStorage:', error);
  }
}

/**
 * Generate a unique ID
 */
function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Format timestamp to readable date
 */
export function formatTimestamp(timestamp: number): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diffInHours = (now.getTime() - date.getTime()) / (1000 * 60 * 60);

  if (diffInHours < 24) {
    return date.toLocaleTimeString('en-US', { 
      hour: 'numeric', 
      minute: '2-digit',
      hour12: true 
    });
  } else if (diffInHours < 48) {
    return 'Yesterday';
  } else if (diffInHours < 168) { // 7 days
    return date.toLocaleDateString('en-US', { weekday: 'short' });
  } else {
    return date.toLocaleDateString('en-US', { 
      month: 'short', 
      day: 'numeric' 
    });
  }
}

/**
 * Format duration in milliseconds to readable string
 */
export function formatDuration(milliseconds: number): string {
  const seconds = Math.floor(milliseconds / 1000);
  
  if (seconds < 60) {
    return `${seconds}s`;
  } else if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return remainingSeconds > 0 ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`;
  } else {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  }
}
