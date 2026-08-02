/**
 * Review Store - Manages review generation data and history
 * Stores everything received from the backend for easy history loading
 */

import { useState, useEffect } from 'react';

export interface ReviewData {
  id: string;
  paperTitle?: string;
  paperIndex: number;
  savedFilepath: string;
  latexContent: string;
  bibliography?: any[];
  papersUsed?: any[];
  statistics?: {
    processed_papers?: number;
    relevant_chunks?: number;
    total_tokens?: number;
    generation_time?: number;
    [key: string]: any;
  };
  reviewFilepath?: string;
  createdAt: number;
  updatedAt: number;
  status: 'generating' | 'completed' | 'error';
  error?: string;
  updates?: Array<{
    type: string;
    message: string;
    timestamp: number;
    result?: any;
  }>;
}

interface ReviewStoreState {
  reviews: Map<string, ReviewData>;
  currentReviewId: string | null;
}

class ReviewStore {
  private static instance: ReviewStore;
  private state: ReviewStoreState;
  private listeners: Set<() => void>;
  private storageKey = 'review-store-data';

  private constructor() {
    this.state = {
      reviews: new Map(),
      currentReviewId: null,
    };
    this.listeners = new Set();
    this.loadFromStorage();
  }

  static getInstance(): ReviewStore {
    if (!ReviewStore.instance) {
      ReviewStore.instance = new ReviewStore();
    }
    return ReviewStore.instance;
  }

  /**
   * Subscribe to store changes
   */
  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Notify all listeners of state changes
   */
  private notify(): void {
    this.listeners.forEach((listener) => listener());
    this.saveToStorage();
  }

  /**
   * Create a new review entry
   */
  createReview(data: {
    paperTitle?: string;
    paperIndex: number;
    savedFilepath: string;
  }): string {
    const id = this.generateId();
    const review: ReviewData = {
      id,
      paperTitle: data.paperTitle,
      paperIndex: data.paperIndex,
      savedFilepath: data.savedFilepath,
      latexContent: '',
      createdAt: Date.now(),
      updatedAt: Date.now(),
      status: 'generating',
      updates: [],
    };

    this.state.reviews.set(id, review);
    this.state.currentReviewId = id;
    this.notify();
    return id;
  }

  /**
   * Update an existing review
   */
  updateReview(id: string, updates: Partial<ReviewData>): void {
    const review = this.state.reviews.get(id);
    if (!review) {
      console.warn(`Review with id ${id} not found`);
      return;
    }

    const updatedReview: ReviewData = {
      ...review,
      ...updates,
      updatedAt: Date.now(),
    };

    this.state.reviews.set(id, updatedReview);
    this.notify();
  }

  /**
   * Add an update/event to a review
   */
  addUpdate(id: string, update: {
    type: string;
    message: string;
    result?: any;
  }): void {
    const review = this.state.reviews.get(id);
    if (!review) return;

    const updates = review.updates || [];
    updates.push({
      ...update,
      timestamp: Date.now(),
    });

    this.updateReview(id, { updates });
  }

  /**
   * Set the LaTeX content for a review
   */
  setLatexContent(id: string, content: string): void {
    const cleanedContent = this.cleanLatexContent(content);
    this.updateReview(id, { latexContent: cleanedContent });
  }

  private cleanLatexContent(content: string): string {
    if (!content) return content;
    
    const lines = content.split('\n');
    
    // Remove first line if it's ```latex or ```
    if (lines.length > 0 && lines[0].trim().match(/^```(latex)?$/)) {
      lines.shift();
    }
    
    // Remove last line if it's ```
    if (lines.length > 0 && lines[lines.length - 1].trim() === '```') {
      lines.pop();
    }
    
    return lines.join('\n');
  }

  /**
   * Mark review as completed with final data
   */
  completeReview(id: string, data: {
    latexContent?: string;
    bibliography?: any[];
    papersUsed?: any[];
    statistics?: any;
    reviewFilepath?: string;
  }): void {
    // Clean LaTeX content if provided
    const cleanedData = {
      ...data,
      latexContent: data.latexContent ? this.cleanLatexContent(data.latexContent) : data.latexContent,
    };
    
    this.updateReview(id, {
      ...cleanedData,
      status: 'completed',
    });
  }

  /**
   * Mark review as errored
   */
  errorReview(id: string, error: string): void {
    this.updateReview(id, {
      status: 'error',
      error,
    });
  }

  /**
   * Get a specific review by ID
   */
  getReview(id: string): ReviewData | undefined {
    return this.state.reviews.get(id);
  }

  /**
   * Get the current active review
   */
  getCurrentReview(): ReviewData | null {
    if (!this.state.currentReviewId) return null;
    return this.state.reviews.get(this.state.currentReviewId) || null;
  }

  /**
   * Get all reviews sorted by creation date (newest first)
   */
  getAllReviews(): ReviewData[] {
    return Array.from(this.state.reviews.values())
      .sort((a, b) => b.createdAt - a.createdAt);
  }

  /**
   * Get reviews by status
   */
  getReviewsByStatus(status: ReviewData['status']): ReviewData[] {
    return this.getAllReviews().filter((review) => review.status === status);
  }

  /**
   * Get reviews for a specific paper
   */
  getReviewsByPaper(savedFilepath: string, paperIndex: number): ReviewData[] {
    return this.getAllReviews().filter(
      (review) => 
        review.savedFilepath === savedFilepath && 
        review.paperIndex === paperIndex
    );
  }

  /**
   * Set the current active review
   */
  setCurrentReview(id: string | null): void {
    this.state.currentReviewId = id;
    this.notify();
  }

  /**
   * Delete a review
   */
  deleteReview(id: string): void {
    this.state.reviews.delete(id);
    if (this.state.currentReviewId === id) {
      this.state.currentReviewId = null;
    }
    this.notify();
  }

  /**
   * Clear all reviews
   */
  clearAllReviews(): void {
    this.state.reviews.clear();
    this.state.currentReviewId = null;
    this.notify();
  }

  /**
   * Get store statistics
   */
  getStatistics() {
    const reviews = this.getAllReviews();
    return {
      total: reviews.length,
      completed: reviews.filter((r) => r.status === 'completed').length,
      generating: reviews.filter((r) => r.status === 'generating').length,
      errored: reviews.filter((r) => r.status === 'error').length,
      totalPapersProcessed: reviews.reduce(
        (sum, r) => sum + (r.statistics?.processed_papers || 0),
        0
      ),
    };
  }

  /**
   * Generate a unique ID for a review
   */
  private generateId(): string {
    return `review_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`;
  }

  /**
   * Save state to localStorage
   */
  private saveToStorage(): void {
    if (typeof window === 'undefined') return;

    try {
      const data = {
        reviews: Array.from(this.state.reviews.entries()),
        currentReviewId: this.state.currentReviewId,
      };
      localStorage.setItem(this.storageKey, JSON.stringify(data));
    } catch (error) {
      console.error('Failed to save review store to localStorage:', error);
    }
  }

  /**
   * Load state from localStorage
   */
  private loadFromStorage(): void {
    if (typeof window === 'undefined') return;

    try {
      const stored = localStorage.getItem(this.storageKey);
      if (stored) {
        const data = JSON.parse(stored);
        this.state.reviews = new Map(data.reviews);
        this.state.currentReviewId = data.currentReviewId;
      }
    } catch (error) {
      console.error('Failed to load review store from localStorage:', error);
    }
  }

  /**
   * Export reviews as JSON
   */
  exportToJSON(): string {
    return JSON.stringify({
      reviews: Array.from(this.state.reviews.entries()),
      exportedAt: Date.now(),
    }, null, 2);
  }

  /**
   * Import reviews from JSON
   */
  importFromJSON(json: string): void {
    try {
      const data = JSON.parse(json);
      if (data.reviews && Array.isArray(data.reviews)) {
        this.state.reviews = new Map(data.reviews);
        this.notify();
      }
    } catch (error) {
      console.error('Failed to import reviews:', error);
      throw new Error('Invalid import data');
    }
  }
}

// Export singleton instance
export const reviewStore = ReviewStore.getInstance();

// Export hook for React components
export function useReviewStore() {
  const [, forceUpdate] = useState({});
  
  useEffect(() => {
    const unsubscribe = reviewStore.subscribe(() => {
      forceUpdate({});
    });
    return unsubscribe;
  }, []);

  return {
    // Current review
    currentReview: reviewStore.getCurrentReview(),
    
    // Review operations
    createReview: (data: Parameters<typeof reviewStore.createReview>[0]) => 
      reviewStore.createReview(data),
    updateReview: (id: string, updates: Partial<ReviewData>) => 
      reviewStore.updateReview(id, updates),
    completeReview: (id: string, data: Parameters<typeof reviewStore.completeReview>[1]) => 
      reviewStore.completeReview(id, data),
    errorReview: (id: string, error: string) => 
      reviewStore.errorReview(id, error),
    deleteReview: (id: string) => 
      reviewStore.deleteReview(id),
    
    // Content operations
    setLatexContent: (id: string, content: string) => 
      reviewStore.setLatexContent(id, content),
    addUpdate: (id: string, update: Parameters<typeof reviewStore.addUpdate>[1]) => 
      reviewStore.addUpdate(id, update),
    
    // Query operations
    getReview: (id: string) => reviewStore.getReview(id),
    getAllReviews: () => reviewStore.getAllReviews(),
    getReviewsByStatus: (status: ReviewData['status']) => 
      reviewStore.getReviewsByStatus(status),
    getReviewsByPaper: (filepath: string, index: number) => 
      reviewStore.getReviewsByPaper(filepath, index),
    
    // Store management
    setCurrentReview: (id: string | null) => reviewStore.setCurrentReview(id),
    clearAllReviews: () => reviewStore.clearAllReviews(),
    getStatistics: () => reviewStore.getStatistics(),
    
    // Import/Export
    exportToJSON: () => reviewStore.exportToJSON(),
    importFromJSON: (json: string) => reviewStore.importFromJSON(json),
  };
}

