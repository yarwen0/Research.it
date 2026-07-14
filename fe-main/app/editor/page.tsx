"use client";
import { useState, useEffect, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { FileEdit, Loader2, CheckCircle, AlertCircle, Download, BookOpen, FileCode } from "lucide-react";
import StatusDisplay from "../_components/status-display";
import ReviewHistorySidebar from "../_components/review-history-sidebar";
import { Nav } from "../_components/nav";
import { SSEUpdate, StatusType, StreamHandler } from "@/lib/stream_handler";
import { useReviewStore } from "@/lib/review-store";
import dynamic from "next/dynamic";
import { SidebarProvider } from "@/components/ui/sidebar";
import { compileLatex } from "@/lib/api";
import { BibliographyDialog } from "../_components/bibliography-dialog";

const LatexMonacoEditor = dynamic(
  () => import("../_components/editor/Latex").then((mod) => {
    const Component = ({ value, onChange }: { value: string; onChange: (value: string | undefined) => void }) => {
      const { LatexMonacoEditor: Editor } = mod as any;
      return <Editor value={value} onChange={onChange} />;
    };
    return Component;
  }),
  { ssr: false }
);

const LatexPreview = dynamic(
  () => import("../_components/editor/Latex").then((mod) => {
    const Component = ({ pdfUrl, isCompiling, error }: { pdfUrl: string | null; isCompiling: boolean; error: string | null }) => {
      const { LatexPreview: Preview } = mod as any;
      return <Preview pdfUrl={pdfUrl} isCompiling={isCompiling} error={error} />;
    };
    return Component;
  }),
  { ssr: false }
);

const TabButton = ({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) => (
  <button
    onClick={onClick}
    className={`px-6 py-3 font-medium transition-colors ${
      active
        ? 'bg-white text-blue-600 border-b-2 border-blue-600'
        : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
    }`}
  >
    {children}
  </button>
);

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";


function EditorPageContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const reviewStore = useReviewStore();
  
  const [activeTab, setActiveTab] = useState<'edit' | 'preview'>('edit');
  const [currentReviewId, setCurrentReviewId] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [updates, setUpdates] = useState<SSEUpdate[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [localLatexContent, setLocalLatexContent] = useState<string>("");
  const [isCompiling, setIsCompiling] = useState(false);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [compilationError, setCompilationError] = useState<string | null>(null);

  const savedFilepath = searchParams.get('filepath');
  const paperIndex = searchParams.get('index');
  const paperTitle = searchParams.get('title');
  const paperInfoParam = searchParams.get('paperInfo');
  const reviewId = searchParams.get('id');

  // Parse paper info from URL parameter
  const paperInfo = paperInfoParam ? JSON.parse(paperInfoParam) : null;

  // Get current review data from store
  const currentReview = currentReviewId ? reviewStore.getReview(currentReviewId) : null;
  const generationComplete = currentReview?.status === 'completed';
  const reviewMetadata = currentReview ? {
    bibliography: currentReview.bibliography,
    papers_used: currentReview.papersUsed,
    statistics: currentReview.statistics,
    review_filepath: currentReview.reviewFilepath,
  } : null;

  // Sync local content with store when review changes or latex content updates
  useEffect(() => {
    if (currentReview && currentReview.latexContent) {
      setLocalLatexContent(currentReview.latexContent);
    }
  }, [currentReview?.id, currentReview?.latexContent]);

  useEffect(() => {
    // If we have a review ID in the URL, load that review
    if (reviewId) {
      const review = reviewStore.getReview(reviewId);
      if (review) {
        setCurrentReviewId(reviewId);
        // Restore the updates if available
        if (review.updates) {
          setUpdates(review.updates.map(u => ({
            status: u.type as StatusType,
            message: u.message,
            result: u.result,
          })));
        }
        return;
      } else {
        setError("Review not found");
        return;
      }
    }

    // Check if we have the necessary parameters for a new review
    if (!savedFilepath || paperIndex === null) {
      // If no parameters, just show empty editor
      return;
    }

    // Check if we already have a review for this paper
    const existingReviews = reviewStore.getReviewsByPaper(savedFilepath, parseInt(paperIndex));
    if (existingReviews.length > 0) {
      const latestReview = existingReviews[0]; // Already sorted by date
      if (latestReview.status === 'completed' || latestReview.status === 'generating') {
        // Load the existing review
        setCurrentReviewId(latestReview.id);
        if (latestReview.updates) {
          setUpdates(latestReview.updates.map(u => ({
            status: u.type as StatusType,
            message: u.message,
            result: u.result,
          })));
        }
        if (latestReview.status === 'generating') {
          setIsGenerating(true);
        }
        return;
      }
    }

    // Start a new review generation
    startReviewGeneration();
  }, [savedFilepath, paperIndex, reviewId]);

  const startReviewGeneration = async () => {
    if (!savedFilepath || paperIndex === null) {
      return;
    }

    // Create a new review entry in the store
    const reviewId = reviewStore.createReview({
      paperTitle: paperTitle || undefined,
      paperIndex: parseInt(paperIndex),
      savedFilepath: savedFilepath,
    });
    
    setCurrentReviewId(reviewId);
    setIsGenerating(true);
    setError(null);
    setUpdates([]);

    try {
      const response = await fetch(`${API_BASE_URL}/api/create_review`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          saved_filepath: savedFilepath,
          paper_index: parseInt(paperIndex),
          paper_info: paperInfo || {
            title: paperTitle || "Untitled",
            keywords: [],
            abstract: "",
          },
        }),
      });

      if (!response.ok) {
        throw new Error(`Failed to start review generation: ${response.statusText}`);
      }

      const streamHandler = new StreamHandler({
        onUpdate: (update) => {
          console.log("SSE Update:", update);
          setUpdates((prev) => [...prev, update]);
          
          // Store update in review store
          reviewStore.addUpdate(reviewId, {
            type: update.status,
            message: update.message,
            result: update.result,
          });
        },
        onProgress: (update) => {
          // Progress update received
        },
        onSuccess: (update) => {
          // Success callback
        },
        onCompleted: (update) => {
          // The data is nested: update.result.result contains the actual review data
          const outerResult = update.result || {};
          const resultData = outerResult.result || outerResult; // Handle both nested and flat structures
          
          // Extract the review data
          const latexContent = resultData.latexContent || resultData.latex_content;
          const bibliography = resultData.bibliography;
          const papersUsed = resultData.papersUsed || resultData.papers_used;
          const statistics = resultData.statistics;
          const reviewFilepath = resultData.reviewFilepath || resultData.review_filepath;
          
          if (latexContent) {
            reviewStore.completeReview(reviewId, {
              latexContent: latexContent,
              bibliography: bibliography,
              papersUsed: papersUsed,
              statistics: statistics,
              reviewFilepath: reviewFilepath,
            });
          }
          
          setIsGenerating(false);
        },
        onError: (errorMessage, update) => {
          console.error("Error:", errorMessage);
          setError(errorMessage);
          reviewStore.errorReview(reviewId, errorMessage);
          setIsGenerating(false);
        },
        onEnd: () => {
          console.log("Stream ended");
          setIsGenerating(false);
        },
      });

      await streamHandler.processStream(response);
    } catch (error) {
      console.error("Error generating review:", error);
      const errorMessage = error instanceof Error ? error.message : "Unknown error";
      setError(errorMessage);
      reviewStore.errorReview(reviewId, errorMessage);
      setIsGenerating(false);
    }
  };

  const handleCompile = async () => {
    if (!localLatexContent.trim()) {
      setCompilationError("No LaTeX content to compile");
      return;
    }

    setIsCompiling(true);
    setCompilationError(null);
    setPdfUrl(null);

    try {
      const blob = await compileLatex(localLatexContent);
      const url = URL.createObjectURL(blob);
      setPdfUrl(url);
      setActiveTab('preview'); // Switch to preview tab automatically
    } catch (error) {
      console.error("Error compiling LaTeX:", error);
      setCompilationError(error instanceof Error ? error.message : "Unknown compilation error");
    } finally {
      setIsCompiling(false);
    }
  };

  const handleSelectReview = (reviewId: string) => {
    router.push(`/editor?id=${reviewId}`);
  };

  const cleanLatexContent = (content: string): string => {
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
  };

  const allReviews = reviewStore.getAllReviews();
  const reviewCount = allReviews.length;

  return (
    <SidebarProvider defaultOpen={false}>
      <ReviewHistorySidebar
        currentReviewId={currentReviewId}
        onSelectReview={handleSelectReview}
      />

      <div className="min-h-screen bg-gray-50 flex flex-col w-full">
        {/* Nav */}
        <Nav />

        {/* Main Content */}
        <div className="flex-1 flex flex-col max-w-7xl mx-auto w-full p-4 pt-20">
        {/* Status Section */}
        <AnimatePresence>
          {(isGenerating || updates.length > 0) && (
            <motion.div
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              className="mb-4"
            >
              <StatusDisplay 
                updates={updates} 
                isLoading={isGenerating}
              />
            </motion.div>
          )}
        </AnimatePresence>

        {/* Error Display */}
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3"
          >
            <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="font-semibold text-red-900">Error</h3>
              <p className="text-sm text-red-700">{error}</p>
              <button
                onClick={() => router.push("/")}
                className="mt-2 text-sm text-red-600 hover:text-red-800 underline"
              >
                Return to home
              </button>
            </div>
          </motion.div>
        )}

        {/* Editor Section */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2 }}
          className="flex-1 flex flex-col bg-white rounded-lg shadow-lg overflow-hidden"
        >
          {/* Tabs */}
          <div className="flex border-b border-gray-300 bg-gray-100">
            <TabButton
              active={activeTab === 'edit'}
              onClick={() => setActiveTab('edit')}
            >
              Edit
            </TabButton>
            <TabButton
              active={activeTab === 'preview'}
              onClick={() => setActiveTab('preview')}
            >
              Preview
            </TabButton>
            <div className="ml-auto flex items-center gap-2 px-4 py-3">
              {generationComplete && (
                <div className="flex items-center gap-2 text-sm text-green-700">
                  <CheckCircle className="w-4 h-4" />
                  <span>Generation Complete</span>
                  {reviewMetadata?.statistics && (
                    <span className="ml-2 text-xs text-gray-600">
                      ({reviewMetadata.statistics.processed_papers} papers, {reviewMetadata.statistics.relevant_chunks} relevant chunks)
                    </span>
                  )}
                </div>
              )}
              {isGenerating && (
                <div className="flex items-center gap-2 text-sm text-blue-700">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Generating...</span>
                </div>
              )}
              <button
                onClick={handleCompile}
                disabled={isCompiling || !localLatexContent.trim()}
                className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-white rounded flex items-center gap-2 text-sm font-medium transition-colors"
              >
                {isCompiling ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Compiling...
                  </>
                ) : (
                  <>
                    <FileCode className="w-4 h-4" />
                    Compile
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Content Area */}
          <div className="flex-1 overflow-hidden">
            {activeTab === 'edit' ? (
              <LatexMonacoEditor
                value={localLatexContent}
                onChange={(value: string | undefined) => {
                  const rawContent = value || '';
                  const cleanedContent = cleanLatexContent(rawContent);
                  setLocalLatexContent(cleanedContent);
                  if (currentReviewId) {
                    reviewStore.setLatexContent(currentReviewId, cleanedContent);
                  }
                }}
              />
            ) : (
              <LatexPreview 
                pdfUrl={pdfUrl} 
                isCompiling={isCompiling} 
                error={compilationError} 
              />
            )}
          </div>

          {/* Footer */}
          <div className="bg-gray-100 border-t border-gray-300 px-4 py-2 flex items-center justify-between">
            <div className="text-sm text-gray-600">
              <span className="font-medium">Tips:</span> Click &quot;Compile&quot; to generate a PDF preview of your LaTeX document
            </div>
            {generationComplete && reviewMetadata && (
              <div className="flex items-center gap-2">
                {reviewMetadata.bibliography && reviewMetadata.bibliography.length > 0 && (
                  <BibliographyDialog bibliography={reviewMetadata.bibliography} />
                )}
                <button
                  onClick={() => {
                    const blob = new Blob([localLatexContent], { type: 'text/plain' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'review.tex';
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                  className="px-3 py-1 text-xs bg-green-100 hover:bg-green-200 text-green-700 rounded flex items-center gap-1"
                >
                  <Download className="w-3 h-3" />
                  Download LaTeX
                </button>
              </div>
            )}
          </div>
        </motion.div>
        </div>
      </div>
    </SidebarProvider>
  );
}

export default function EditorPage() {
  return (
    <Suspense fallback={null}>
      <EditorPageContent />
    </Suspense>
  );
}
