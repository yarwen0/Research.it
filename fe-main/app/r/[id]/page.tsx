"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import ChatInput, { SpeedMode } from "@/app/_components/chat-input";
import StatusDisplay from "@/app/_components/status-display";
import ResearchGraph from "@/app/_components/research-graph";
import ResearchResults from "@/app/_components/research-results";
import { Nav } from "@/app/_components/nav";
import { HistorySidebar } from "@/app/_components/history-sidebar";
import { submitResearch } from "@/lib/api";
import { SSEUpdate } from "@/lib/stream_handler";
import { SidebarProvider, SidebarInset, useSidebar } from "@/components/ui/sidebar";
import { getResponseById, saveResponse, type ResearchResponse } from "@/lib/response-store";
import { ensureFrontendFormat, transformPapers } from "@/lib/paper-transform";

const SPEED_CONFIG = {
  fast: { num_topics: 2, papers_per_topic: 2 },
  medium: { num_topics: 5, papers_per_topic: 5 },
  slow: { num_topics: 10, papers_per_topic: 5 },
};

function ResearchDetailContent() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  
  // Initial data loading
  const [response, setResponse] = useState<ResearchResponse | null>(null);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  
  // Research state (same as main page)
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [updates, setUpdates] = useState<SSEUpdate[]>([]);
  const [showGraph, setShowGraph] = useState(false);
  const [researchPapers, setResearchPapers] = useState<any[]>([]);
  const [researchMetrics, setResearchMetrics] = useState<any>(null);
  const [researchDatasets, setResearchDatasets] = useState<any>(null);
  const [isStatusExpanded, setIsStatusExpanded] = useState(false);
  const [speedMode, setSpeedMode] = useState<SpeedMode>('fast');
  const [currentPrompt, setCurrentPrompt] = useState("");

  useEffect(() => {
    if (id) {
      const data = getResponseById(id);
      if (data) {
        setResponse(data);
        setCurrentPrompt(data.prompt);
        
        // Priority: suggested_papers (already in frontend format) > papers > processed_papers
        if (data.suggested_papers && data.suggested_papers.length > 0) {
          // Backend already provided frontend-ready format
          setResearchPapers(data.suggested_papers);
        } else {
          // Fallback: transform papers if needed
          const rawPapers = data.papers || data.processed_papers || [];
          const transformedPapers = ensureFrontendFormat(rawPapers);
          setResearchPapers(transformedPapers);
        }
        
        setResearchMetrics(data.metrics || data.trends);
        setResearchDatasets(data.datasets || null);
        setSpeedMode(data.speedMode);
        setShowGraph(true);
        // Load progress updates if available
        if (data.progressUpdates) {
          setUpdates(data.progressUpdates);
        }
      }
      setIsInitialLoading(false);
      
      if (!data) {
        // Redirect to home if response not found
        setTimeout(() => router.push("/"), 2000);
      }
    }
  }, [id, router]);

  const handleSendMessage = async () => {
    if (!input.trim() || isLoading) return;

    console.log("Sending message:", input);
    const promptText = input;
    setCurrentPrompt(promptText);
    setIsLoading(true);
    setUpdates([]);

    const config = SPEED_CONFIG[speedMode];
    
    // Array to collect all progress updates
    const collectedUpdates: any[] = [];

    try {
      await submitResearch(input, config.num_topics, config.papers_per_topic, {
        onUpdate: (update) => {
          console.log("Update:", update);
          setUpdates((prev) => [...prev, update]);
          collectedUpdates.push(update);
        },
        onProgress: (update) => {
          console.log("Progress:", update.result);
        },
        onCompleted: (update) => {
          console.log("Completed:", update.result);
          setIsLoading(false);
          setShowGraph(true);
          
          // Backend now returns suggested_papers in frontend format (title, keywords, abstract)
          if (update.result?.suggested_papers && Array.isArray(update.result.suggested_papers)) {
            console.log("Setting suggested papers:", update.result.suggested_papers.length);
            console.log("First suggested paper:", update.result.suggested_papers[0]);
            setResearchPapers(update.result.suggested_papers);
          } else {
            console.warn("No suggested_papers found, falling back to processed_papers transformation");
            // Fallback: transform processed_papers if suggested_papers not available
            if (update.result?.processed_papers && Array.isArray(update.result.processed_papers)) {
              const transformedPapers = transformPapers(update.result.processed_papers);
              setResearchPapers(transformedPapers);
            }
          }
          
          // Extract metrics from the result (under trends key)
          if (update.result?.trends) {
            console.log("Setting research metrics:", update.result.trends);
            setResearchMetrics(update.result.trends);
          } else {
            console.warn("No trends found in result:", update.result);
          }
          
          // Extract datasets from the result
          if (update.result?.datasets) {
            console.log("Setting research datasets:", update.result.datasets);
            setResearchDatasets(update.result.datasets);
          } else {
            console.warn("No datasets found in result:", update.result);
          }
          
          // Save the completed response to localStorage with all backend data
          const savedResponse = saveResponse({
            prompt: promptText,
            user_prompt: update.result?.user_prompt || promptText,
            topics: update.result?.topics || [],
            total_papers: update.result?.total_papers || 0,
            processed_papers: update.result?.processed_papers || [], // Raw papers for reference
            suggested_papers: update.result?.suggested_papers || [], // Frontend-ready papers
            saved_filepath: update.result?.saved_filepath,
            trends: update.result?.trends || null,
            datasets: update.result?.datasets || null,
            progressUpdates: collectedUpdates,
            // Keep legacy fields for backward compatibility
            papers: update.result?.suggested_papers || update.result?.processed_papers || [],
            metrics: update.result?.trends || null,
            graphData: update.result,
            speedMode: speedMode,
          });
          console.log("Saved response with ID:", savedResponse.id);
          
          router.push(`/r/${savedResponse.id}`);
        },
        onError: (error) => {
          console.error("Error:", error);
          setIsLoading(false);
        },
        onEnd: () => {
          console.log("Stream ended");
          setIsLoading(false);
        },
      });
    } catch (error) {
      console.error("Failed to submit research:", error);
      setIsLoading(false);
    }

    setInput("");
  };

  const handleSelectResponse = (selectedResponse: ResearchResponse) => {
    router.push(`/r/${selectedResponse.id}`);
  };

  if (isInitialLoading) {
    return (
      <>
        <HistorySidebar
          onSelectResponse={handleSelectResponse}
          currentResponseId={id}
        />
        <SidebarInset>
          <div className="flex h-screen items-center justify-center bg-gradient-to-br from-purple-50 via-pink-50 to-blue-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
            <div className="text-center">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-600 mx-auto mb-4"></div>
              <p className="text-gray-600 dark:text-gray-400">Loading research...</p>
            </div>
          </div>
        </SidebarInset>
      </>
    );
  }

  if (!response) {
    return (
      <>
        <HistorySidebar
          onSelectResponse={handleSelectResponse}
          currentResponseId={id}
        />
        <SidebarInset>
          <div className="flex h-screen items-center justify-center bg-gradient-to-br from-purple-50 via-pink-50 to-blue-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
            <div className="text-center">
              <div className="h-16 w-16 text-gray-400 mx-auto mb-4 text-4xl">🔍</div>
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
                Research Not Found
              </h2>
              <p className="text-gray-600 dark:text-gray-400 mb-4">
                This research result doesn't exist or has been deleted.
              </p>
              <button 
                onClick={() => router.push("/")}
                className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors"
              >
                ← Back to Home
              </button>
            </div>
          </div>
        </SidebarInset>
      </>
    );
  }

  return (
    <>
      <HistorySidebar
        onSelectResponse={handleSelectResponse}
        currentResponseId={id}
      />
      <SidebarInset>
        <Nav title={showGraph && currentPrompt ? currentPrompt : undefined} />
        <main className={`flex min-h-screen flex-col items-center p-4 py-8 pt-24 transition-all duration-500 ${!showGraph && !isLoading ? 'justify-center' : ''}`}>
          <div className="w-full max-w-6xl flex flex-col items-center gap-8">
            <AnimatePresence mode="wait">
              {showGraph && (
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -20 }}
                  transition={{ duration: 0.5, ease: "easeOut" }}
                  className="w-full space-y-4"
                >
                  <ResearchGraph 
                    nodes={response.graphData?.nodes} 
                    edges={response.graphData?.edges}
                  />
                </motion.div>
              )}
            </AnimatePresence>

            <AnimatePresence mode="wait">
              {showGraph && researchPapers.length > 0 && (
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -20 }}
                  transition={{ duration: 0.5, delay: 0.2, ease: "easeOut" }}
                  className="w-full"
                >
                  <ResearchResults 
                    papers={researchPapers} 
                    metrics={researchMetrics} 
                    datasets={researchDatasets}
                    processedPapers={response.processed_papers || []}
                  />
                </motion.div>
              )}
            </AnimatePresence>

            {/* Input Component - centered when alone, moved down when graph shows */}
            <motion.div
              layout
              transition={{ duration: 0.5, ease: "easeOut" }}
              className={`w-full ${!showGraph && !isLoading && updates.length === 0 ? 'max-w-3xl' : ''}`}
            >
              <ChatInput
                input={input}
                setInput={setInput}
                onSendMessage={handleSendMessage}
                isLoading={isLoading}
                placeholder="Refine your research focus..."
                variant="homepage-initial"
                speedMode={speedMode}
                onSpeedModeChange={setSpeedMode}
              />
            </motion.div>

            {/* Status Display - below input, collapsible when graph is active */}
            <AnimatePresence mode="wait">
              {(updates.length > 0 || isLoading) && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.3, ease: "easeOut" }}
                  className="w-full"
                >
                  {showGraph && !isLoading ? (
                    <div className="w-full">
                      <button
                        onClick={() => setIsStatusExpanded(!isStatusExpanded)}
                        className="w-full flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-800 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                      >
                        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                          Research Progress Details
                        </span>
                        <motion.div
                          animate={{ rotate: isStatusExpanded ? 180 : 0 }}
                          transition={{ duration: 0.3 }}
                        >
                          <svg
                            className="w-5 h-5 text-gray-500"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M19 9l-7 7-7-7"
                            />
                          </svg>
                        </motion.div>
                      </button>
                      <AnimatePresence>
                        {isStatusExpanded && (
                          <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: "auto", opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            transition={{ duration: 0.3 }}
                            className="overflow-hidden"
                          >
                            <div className="pt-4">
                              <StatusDisplay updates={updates} isLoading={isLoading} />
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  ) : (
                    <StatusDisplay updates={updates} isLoading={isLoading} />
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </main>
      </SidebarInset>
    </>
  );
}

export default function ResearchDetailPage() {
  return (
    <SidebarProvider defaultOpen={false}>
      <ResearchDetailContent />
    </SidebarProvider>
  );
}
