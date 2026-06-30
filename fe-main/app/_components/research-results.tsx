"use client";
import { motion, AnimatePresence } from "framer-motion";
import { BookOpen, Tag, FileText, Database, FileSearch, FileEdit, ChevronLeft, ChevronRight, ExternalLink, BarChart3 } from "lucide-react";
import { useState } from "react";
import { useRouter } from "next/navigation";
import MetricsChart from "./metrics-chart";
import PaperList from "./paper-list";
import DatasetList from "./dataset-list";
import { getStoredResponses } from "@/lib/response-store";
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from "@/components/ui/drawer";
import { Button } from "@/components/ui/button";

interface ResearchPaper {
  title: string;
  keywords: string[];
  abstract: string;
}

interface ResearchResultsProps {
  papers: ResearchPaper[];
  metrics?: any; // Metrics data from backend
  datasets?: any; // Datasets data from backend
  processedPapers?: any[]; // Raw processed papers for topics lookup
}

type TabType = "datasets" | "metrics" | null;

const tabs: { id: TabType; label: string; icon: typeof Database; disabled?: boolean }[] = [
  { id: "datasets", label: "Datasets", icon: Database },
];

export default function ResearchResults({ papers, metrics, datasets, processedPapers = [] }: ResearchResultsProps) {
  const router = useRouter();
  const [selectedPaperIndex, setSelectedPaperIndex] = useState<number>(0);
  const [selectedDatasetIndex, setSelectedDatasetIndex] = useState<number>(-1);
  const [activeTab, setActiveTab] = useState<TabType>("datasets");
  const [isPaperSidebarOpen, setIsPaperSidebarOpen] = useState<boolean>(false);
  const [isDatasetSidebarOpen, setIsDatasetSidebarOpen] = useState<boolean>(false);
  const [isAnalyticsOpen, setIsAnalyticsOpen] = useState<boolean>(false);

  const handleCreateReview = () => {
    const responses = getStoredResponses();
    if (responses.length === 0) {
      alert("No research session found. Please run a research query first.");
      return;
    }

    // Get the most recent response (current session)
    const currentResponse = responses[0];
    const savedFilepath = currentResponse.saved_filepath;

    if (!savedFilepath) {
      alert("No saved filepath found for the current session.");
      return;
    }

    // Get the selected paper information
    const selectedPaper = papers[selectedPaperIndex];
    if (!selectedPaper) {
      alert("Please select a paper first.");
      return;
    }

    // Redirect to editor page with query parameters
    // Include paper info as JSON string in URL
    const params = new URLSearchParams({
      filepath: savedFilepath,
      index: selectedPaperIndex.toString(),
      title: selectedPaper.title,
      paperInfo: JSON.stringify({
        title: selectedPaper.title,
        keywords: selectedPaper.keywords,
        abstract: selectedPaper.abstract,
      }),
    });
    
    router.push(`/editor?${params.toString()}`);
  };

  if (!papers || papers.length === 0) {
    return null;
  }

  const selectedPaper = papers[selectedPaperIndex] ? papers[selectedPaperIndex] : null;
  const selectedDataset = datasets?.datasets && selectedDatasetIndex >= 0 
    ? datasets.datasets[selectedDatasetIndex] 
    : null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.2 }}
      className="w-full relative"
    >
      {/* Main Content Area with Sidebar */}
      <div className="relative flex gap-4">
        {/* Floating Toggle Button - Left (Datasets) */}
        {!isDatasetSidebarOpen && datasets?.datasets && datasets.datasets.length > 0 && (
          <motion.button
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            onClick={() => setIsDatasetSidebarOpen(true)}
            className="fixed left-4 top-32 z-40 p-3 bg-green-600 dark:bg-green-500 text-white rounded-full shadow-lg hover:bg-green-700 dark:hover:bg-green-600 transition-all duration-200 hover:scale-110"
            title="View Datasets"
          >
            <Database className="w-5 h-5" />
          </motion.button>
        )}

        {/* Collapsible Left Sidebar - Datasets */}
        <AnimatePresence>
          {isDatasetSidebarOpen && datasets?.datasets && (
            <motion.div
              initial={{ x: "-100%", opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: "-100%", opacity: 0 }}
              transition={{ duration: 0.3, ease: "easeInOut" }}
              className="fixed left-0 top-0 h-screen w-[500px] bg-white dark:bg-gray-900 shadow-2xl z-50 overflow-hidden flex flex-col"
            >
              {/* Sidebar Header */}
              <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800">
                <div className="flex items-center gap-2">
                  <Database className="w-5 h-5 text-green-600 dark:text-green-400" />
                  <h3 className="font-semibold text-gray-900 dark:text-gray-100">
                    Datasets
                  </h3>
                  <span className="text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 px-2 py-1 rounded-full">
                    {datasets.datasets.length}
                  </span>
                </div>
                <button
                  onClick={() => setIsDatasetSidebarOpen(false)}
                  className="p-2 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-lg transition-colors"
                  title="Close sidebar"
                >
                  <ChevronLeft className="w-5 h-5 text-gray-600 dark:text-gray-400" />
                </button>
              </div>

              {/* Sidebar Content */}
              <div className="flex-1 overflow-y-auto p-3">
                <DatasetList
                  datasets={datasets.datasets}
                  selectedIndex={selectedDatasetIndex}
                  onSelectDataset={setSelectedDatasetIndex}
                  totalDatasets={datasets.total_unique_datasets}
                  pieChart={datasets.pie_chart}
                  expandedDetails={
                    selectedDataset && selectedDatasetIndex >= 0 ? (
                      <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="mt-2 p-4 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700"
                      >
                        {/* All Aliases */}
                        <div className="mb-4">
                          <h5 className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">
                            All Aliases
                          </h5>
                          <div className="flex flex-wrap gap-1.5">
                            {selectedDataset.original_names.map((name: string, idx: number) => (
                              <span
                                key={idx}
                                className="px-2 py-1 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 text-xs rounded-full font-medium"
                              >
                                {name}
                              </span>
                            ))}
                          </div>
                        </div>

                        {/* Papers using this dataset */}
                        <div className="mb-4">
                          <h5 className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">
                            Papers ({selectedDataset.papers.length})
                          </h5>
                          <div className="space-y-2 max-h-64 overflow-y-auto">
                            {selectedDataset.papers.map((paper: any, idx: number) => (
                              <div
                                key={idx}
                                className="p-2 bg-white dark:bg-gray-700 rounded border border-gray-200 dark:border-gray-600"
                              >
                                <p className="text-xs text-gray-900 dark:text-gray-100 font-medium mb-1">
                                  {paper.title}
                                </p>
                                <p className="text-xs text-gray-500 dark:text-gray-400">
                                  Referenced as: <span className="font-medium">{paper.original_name_used}</span>
                                </p>
                              </div>
                            ))}
                          </div>
                        </div>

                        {/* Google Search Link */}
                        <a
                          href={`https://www.google.com/search?q=${encodeURIComponent(selectedDataset.normalized_id + " dataset")}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="w-full p-2.5 rounded-lg bg-green-600 hover:bg-green-700 dark:bg-green-600 dark:hover:bg-green-700 text-white font-semibold shadow-md hover:shadow-lg transition-all duration-200 flex items-center justify-center gap-2"
                        >
                          <ExternalLink className="w-4 h-4" />
                          Search on Google
                        </a>
                      </motion.div>
                    ) : undefined
                  }
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Backdrop for left sidebar */}
        <AnimatePresence>
          {isDatasetSidebarOpen && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              onClick={() => setIsDatasetSidebarOpen(false)}
              className="fixed inset-0 bg-black/20 dark:bg-black/40 z-40 backdrop-blur-sm"
            />
          )}
        </AnimatePresence>

        {/* Floating Toggle Button */}
        {!isPaperSidebarOpen && (
          <motion.button
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
            onClick={() => setIsPaperSidebarOpen(true)}
            className="fixed right-4 top-32 z-40 p-3 bg-blue-600 dark:bg-blue-500 text-white rounded-full shadow-lg hover:bg-blue-700 dark:hover:bg-blue-600 transition-all duration-200 hover:scale-110"
            title="View Suggested Papers"
          >
            <BookOpen className="w-5 h-5" />
          </motion.button>
        )}

        {/* Collapsible Right Sidebar - Papers */}
        <AnimatePresence>
          {isPaperSidebarOpen && (
            <motion.div
              initial={{ x: "100%", opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: "100%", opacity: 0 }}
              transition={{ duration: 0.3, ease: "easeInOut" }}
              className="fixed right-0 top-0 h-screen w-[500px] bg-white dark:bg-gray-900 shadow-2xl z-50 overflow-hidden flex flex-col"
            >
              {/* Sidebar Header */}
              <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800">
                <div className="flex items-center gap-2">
                  <BookOpen className="w-5 h-5 text-blue-600 dark:text-blue-400" />
                  <h3 className="font-semibold text-gray-900 dark:text-gray-100">
                    Suggested Papers
                  </h3>
                  <span className="text-xs bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 px-2 py-1 rounded-full">
                    {papers.length}
                  </span>
                </div>
                <button
                  onClick={() => setIsPaperSidebarOpen(false)}
                  className="p-2 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-lg transition-colors"
                  title="Close sidebar"
                >
                  <ChevronRight className="w-5 h-5 text-gray-600 dark:text-gray-400" />
                </button>
              </div>

              {/* Sidebar Content */}
              <div className="flex-1 overflow-y-auto p-3">
                {/* Paper List with Inline Expansion */}
                <PaperList
                  papers={papers}
                  selectedIndex={selectedPaperIndex}
                  onSelectPaper={setSelectedPaperIndex}
                  expandedDetails={
                    selectedPaper && selectedPaperIndex >= 0 ? (
                      <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="mt-2 p-4 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700"
                      >
                        {/* All Keywords */}
                        <div className="mb-4">
                          <div className="flex items-center gap-2 mb-2">
                            <Tag className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" />
                            <h5 className="text-xs font-semibold text-gray-700 dark:text-gray-300">
                              All Keywords
                            </h5>
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {selectedPaper.keywords.map((keyword, keyIndex) => (
                              <span
                                key={keyIndex}
                                className="px-2 py-1 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 text-xs rounded-full font-medium"
                              >
                                {keyword}
                              </span>
                            ))}
                          </div>
                        </div>

                        {/* Abstract */}
                        <div className="mb-4">
                          <div className="flex items-center gap-2 mb-2">
                            <FileText className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" />
                            <h5 className="text-xs font-semibold text-gray-700 dark:text-gray-300">
                              Abstract
                            </h5>
                          </div>
                          <p className="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
                            {selectedPaper.abstract}
                          </p>
                        </div>

                        {/* Create Review Button */}
                        <button
                          onClick={handleCreateReview}
                          className="w-full p-2.5 rounded-lg bg-blue-600 hover:bg-blue-700 dark:bg-blue-600 dark:hover:bg-blue-700 text-white font-semibold shadow-md hover:shadow-lg transition-all duration-200 flex items-center justify-center gap-2"
                        >
                          <FileEdit className="w-4 h-4" />
                          Create Review
                        </button>
                      </motion.div>
                    ) : undefined
                  }
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Backdrop */}
        <AnimatePresence>
          {isPaperSidebarOpen && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              onClick={() => setIsPaperSidebarOpen(false)}
              className="fixed inset-0 bg-black/20 dark:bg-black/40 z-40 backdrop-blur-sm"
            />
          )}
        </AnimatePresence>
      </div>

      {/* Analytics Drawer - Bottom Center */}
      <Drawer open={isAnalyticsOpen} onOpenChange={setIsAnalyticsOpen}>
        <DrawerTrigger asChild>
          <motion.button
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.4 }}
            className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 p-3 bg-purple-600 dark:bg-purple-500 text-white rounded-full shadow-lg hover:bg-purple-700 dark:hover:bg-purple-600 transition-all duration-200 hover:scale-110 flex items-center gap-2"
            title="View Analytics"
          >
            <BarChart3 className="w-5 h-5" />
          </motion.button>
        </DrawerTrigger>
        <DrawerContent className="max-h-[85vh]">
          <DrawerHeader>
            <DrawerTitle className="flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-purple-600 dark:text-purple-400" />
              Research Analytics
            </DrawerTitle>
            <DrawerDescription>
              Comprehensive metrics and insights from your research analysis
            </DrawerDescription>
          </DrawerHeader>
          <div className="overflow-y-auto px-4 pb-4">
            {metrics ? (
              <MetricsChart metrics={metrics} processedPapers={processedPapers} />
            ) : (
              <div className="flex items-center justify-center h-[400px] bg-gray-50 dark:bg-gray-800/50 rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-700">
                <div className="text-center">
                  <FileSearch className="w-16 h-16 mx-auto mb-4 text-gray-400 dark:text-gray-600" />
                  <p className="text-lg font-medium text-gray-600 dark:text-gray-400">
                    No metrics data available
                  </p>
                  <p className="text-sm text-gray-500 dark:text-gray-500 mt-2">
                    Metrics will be displayed here once the research analysis is complete
                  </p>
                </div>
              </div>
            )}
          </div>
          <DrawerFooter>
            <DrawerClose asChild>
              <Button variant="outline">Close</Button>
            </DrawerClose>
          </DrawerFooter>
        </DrawerContent>
      </Drawer>
    </motion.div>
  );
}
