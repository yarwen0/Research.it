"use client";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import ChatInput, { SpeedMode } from "./_components/chat-input";
import StatusDisplay from "./_components/status-display";
import ResearchGraph from "./_components/research-graph";
import ResearchResults from "./_components/research-results";
import { Nav } from "./_components/nav";
import { HistorySidebar } from "./_components/history-sidebar";
import { submitResearch, fetchGraph } from "@/lib/api";
import { SSEUpdate } from "@/lib/stream_handler";
import { saveResponse, type ResearchResponse } from "@/lib/response-store";
import { ensureFrontendFormat, transformPapers } from "@/lib/paper-transform";
import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar";

const SPEED_CONFIG = {
  fast: { num_topics: 2, papers_per_topic: 2 },
  medium: { num_topics: 5, papers_per_topic: 5 },
  slow: { num_topics: 10, papers_per_topic: 5 },
};

export default function Home() {
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [updates, setUpdates] = useState<SSEUpdate[]>([]);
  const [showGraph, setShowGraph] = useState(false);
  const [hasStartedResearch, setHasStartedResearch] = useState(false);
  const [researchPapers, setResearchPapers] = useState<any[]>([]);
  const [researchMetrics, setResearchMetrics] = useState<any>(null);
  const [researchDatasets, setResearchDatasets] = useState<any>(null);
  const [processedPapers, setProcessedPapers] = useState<any[]>([]); // Raw processed papers
  const [isStatusExpanded, setIsStatusExpanded] = useState(true);
  const [speedMode, setSpeedMode] = useState<SpeedMode>('fast');
  const [currentResponseId, setCurrentResponseId] = useState<string | undefined>(undefined);
  const [currentPrompt, setCurrentPrompt] = useState("");
  const [researchStartTime, setResearchStartTime] = useState<number | null>(null);
  const [graphNodes, setGraphNodes] = useState<any[]>([]);
  const [graphEdges, setGraphEdges] = useState<any[]>([]);

  const handleSendMessage = async () => {
    if (!input.trim() || isLoading) return;

    const promptText = input;
    setCurrentPrompt(promptText);
    setIsLoading(true);
    setUpdates([]);
    setHasStartedResearch(true);
    setGraphNodes([]);
    setGraphEdges([]);
    
    // Record start time
    const startTime = Date.now();
    setResearchStartTime(startTime);

    const config = SPEED_CONFIG[speedMode];
    
    // Array to collect all progress updates
    const collectedUpdates: any[] = [];

    try {
      await submitResearch(input, config.num_topics, config.papers_per_topic, {
        onUpdate: (update) => {
          // Add timestamp to each update
          const timestampedUpdate = {
            ...update,
            timestamp: Date.now(),
          };
          setUpdates((prev) => [...prev, timestampedUpdate]);
          collectedUpdates.push(timestampedUpdate);
        },
        onProgress: () => {},
        onCompleted: (update) => {
          setIsLoading(false);
          setShowGraph(true);

          // Fetch real citation graph if project_id is available
          if (update.result?.project_id) {
            fetchGraph(update.result.project_id).then((graphData) => {
              if (graphData?.nodes) {
                setGraphNodes(graphData.nodes.map((n: any) => ({
                  id: n.data.id,
                  label: n.data.title || n.data.label || n.data.id,
                  type: n.data.node_type || "paper",
                })));
              }
              if (graphData?.edges) {
                setGraphEdges(graphData.edges.map((e: any) => ({
                  source: e.data.source,
                  target: e.data.target,
                  label: e.data.edge_type,
                })));
              }
            }).catch(console.error);
          }

          // Calculate end time and duration
          const endTime = Date.now();
          const duration = startTime ? endTime - startTime : 0;
          
          // Backend now returns suggested_papers in frontend format (title, keywords, abstract)
          if (update.result?.suggested_papers && Array.isArray(update.result.suggested_papers)) {
            setResearchPapers(update.result.suggested_papers);
          } else {
            console.warn("No suggested_papers found, falling back to processed_papers transformation");
            // Fallback: transform processed_papers if suggested_papers not available
            if (update.result?.processed_papers && Array.isArray(update.result.processed_papers)) {
              const transformedPapers = transformPapers(update.result.processed_papers);
              setResearchPapers(transformedPapers);
            }
          }
          
          // Store processed_papers for topics lookup
          if (update.result?.processed_papers && Array.isArray(update.result.processed_papers)) {
            setProcessedPapers(update.result.processed_papers);
          }
          
          // Extract metrics from the result (under trends key)
          if (update.result?.trends) {
            setResearchMetrics(update.result.trends);
          } else {
            console.warn("No trends found in result:", update.result);
          }
          
          // Extract datasets from the result
          if (update.result?.datasets) {
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
            project_id: update.result?.project_id,
            trends: update.result?.trends || null,
            datasets: update.result?.datasets || null,
            progressUpdates: collectedUpdates,
            // Timing information
            startTime: startTime,
            endTime: endTime,
            duration: duration,
            // Keep legacy fields for backward compatibility
            papers: update.result?.suggested_papers || update.result?.processed_papers || [],
            metrics: update.result?.trends || null,
            graphData: update.result,
            speedMode: speedMode,
          });
          setCurrentResponseId(savedResponse.id);
        },
        onError: (error) => {
          console.error("Error:", error);
          setIsLoading(false);
        },
        onEnd: () => {
          setIsLoading(false);
        },
      });
    } catch (error) {
      console.error("Failed to submit research:", error);
      setIsLoading(false);
    }

    setInput("");
  };

  const handleSelectResponse = (response: ResearchResponse) => {
    setCurrentResponseId(response.id);
    setCurrentPrompt(response.prompt);
    
    // Priority: suggested_papers (already in frontend format) > papers > processed_papers
    if (response.suggested_papers && response.suggested_papers.length > 0) {
      // Backend already provided frontend-ready format
      setResearchPapers(response.suggested_papers);
    } else {
      // Fallback: transform papers if needed
      const rawPapers = response.papers || response.processed_papers || [];
      const transformedPapers = ensureFrontendFormat(rawPapers);
      setResearchPapers(transformedPapers);
    }
    
    setResearchMetrics(response.metrics || response.trends);
    setResearchDatasets(response.datasets || null);
    setShowGraph(true);
    setHasStartedResearch(true);
    setSpeedMode(response.speedMode);
    setGraphNodes([]);
    setGraphEdges([]);
    if ((response as any).project_id) {
      fetchGraph((response as any).project_id).then((graphData) => {
        if (graphData?.nodes) {
          setGraphNodes(graphData.nodes.map((n: any) => ({
            id: n.data.id,
            label: n.data.title || n.data.label || n.data.id,
            type: n.data.node_type || "paper",
          })));
        }
        if (graphData?.edges) {
          setGraphEdges(graphData.edges.map((e: any) => ({
            source: e.data.source,
            target: e.data.target,
            label: e.data.edge_type,
          })));
        }
      }).catch(console.error);
    }
  };

  return (
    <SidebarProvider defaultOpen={false}>
      <HistorySidebar
        onSelectResponse={handleSelectResponse}
        currentResponseId={currentResponseId}
        enableNavigation={true}
      />
      <SidebarInset>
        <Nav title={showGraph && currentPrompt ? currentPrompt : undefined} />
        <main className={`flex min-h-screen flex-col items-center p-4 py-8 pt-24 transition-all duration-500 ${!showGraph && !isLoading ? 'justify-center' : ''}`}>
          <div className="w-full max-w-6xl flex flex-col items-center gap-8">

        {/* Research Graph - shown after completion - MAIN FOCUS */}
        <AnimatePresence mode="wait">
          {showGraph && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.5, ease: "easeOut" }}
              className="w-full space-y-4"
            >
              <h2 className="text-xl font-semibold text-gray-700 dark:text-gray-300">Citation Network</h2>
              <ResearchGraph nodes={graphNodes.length > 0 ? graphNodes : undefined} edges={graphEdges.length > 0 ? graphEdges : undefined} />
            </motion.div>
          )}
        </AnimatePresence>

        {/* Research Results - shown after completion */}
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
                processedPapers={processedPapers}
              />
            </motion.div>
          )}
        </AnimatePresence>

        {/* Heading - only shown on initial state */}
        <AnimatePresence>
          {!showGraph && !isLoading && updates.length === 0 && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.3 }}
              className="text-center"
            >
              <h1 className="text-2xl sm:text-3xl font-bold text-blue-600 dark:text-blue-400">
                Your Intelligent Research Companion
              </h1>
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
            placeholder={hasStartedResearch ? "Refine your research focus..." : "Enter your research query... (e.g., 'hand pose estimation using deep learning')"}
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
    </SidebarProvider>
  );
}
