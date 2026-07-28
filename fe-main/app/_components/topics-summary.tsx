"use client";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronRight, BookOpen, Tag, Calendar, Users as UsersIcon, ExternalLink } from "lucide-react";
import { useState, useEffect } from "react";
import { getStoredResponses } from "@/lib/response-store";

interface Topic {
  topic: string;
  paper_ids: string[];
}

interface TopicsSummary {
  total_topics: number;
  topics: Topic[];
}

interface TopicsSummaryProps {
  topicsSummary: TopicsSummary;
  processedPapers?: any[]; // Papers from the current research response
}

interface PaperDetails {
  paper_id: string;
  title: string;
  authors?: string[];
  date?: string;
  abstract?: string;
  keywords?: string[];
  pdf_url?: string;
}

export default function TopicsSummary({ topicsSummary, processedPapers = [] }: TopicsSummaryProps) {
  const [expandedTopics, setExpandedTopics] = useState<Set<string>>(new Set());
  const [papersMap, setPapersMap] = useState<Map<string, PaperDetails>>(new Map());

  // Load paper details from provided processedPapers or fallback to localStorage
  useEffect(() => {
    const paperDetailsMap = new Map<string, PaperDetails>();

    // First, try to use the provided processedPapers from current response
    if (processedPapers && processedPapers.length > 0) {
      processedPapers.forEach((paper: any) => {
        if (paper.paper_id) {
          // Handle multiple possible data structures
          const title = paper.title || paper.normalized?.title || paper.extraction?.title || "Untitled Paper";
          const authors = paper.authors || paper.normalized?.authors || paper.extraction?.authors || [];
          const date = paper.published || paper.date || paper.normalized?.date || paper.extraction?.date || "";
          const abstract = paper.abstract || paper.normalized?.abstract || paper.extraction?.abstract || "";
          const keywords = paper.keywords || paper.normalized?.keywords || paper.extraction?.keywords || [];
          const pdf_url = paper.pdf_url || paper.normalized?.pdf_url || paper.extraction?.pdf_url || "";

          paperDetailsMap.set(paper.paper_id, {
            paper_id: paper.paper_id,
            title,
            authors,
            date,
            abstract,
            keywords,
            pdf_url,
          });
        }
      });
    } else {
      // Fallback: Load from all stored responses in localStorage
      const responses = getStoredResponses();
      responses.forEach((response) => {
        if (response.processed_papers && Array.isArray(response.processed_papers)) {
          response.processed_papers.forEach((paper: any) => {
            if (paper.paper_id) {
              // Handle multiple possible data structures
              const title = paper.title || paper.normalized?.title || paper.extraction?.title || "Untitled Paper";
              const authors = paper.authors || paper.normalized?.authors || paper.extraction?.authors || [];
              const date = paper.published || paper.date || paper.normalized?.date || paper.extraction?.date || "";
              const abstract = paper.abstract || paper.normalized?.abstract || paper.extraction?.abstract || "";
              const keywords = paper.keywords || paper.normalized?.keywords || paper.extraction?.keywords || [];
              const pdf_url = paper.pdf_url || paper.normalized?.pdf_url || paper.extraction?.pdf_url || "";

              paperDetailsMap.set(paper.paper_id, {
                paper_id: paper.paper_id,
                title,
                authors,
                date,
                abstract,
                keywords,
                pdf_url,
              });
            }
          });
        }
      });
    }

    setPapersMap(paperDetailsMap);
  }, [processedPapers]);

  const toggleTopic = (topic: string) => {
    const newExpanded = new Set(expandedTopics);
    if (newExpanded.has(topic)) {
      newExpanded.delete(topic);
    } else {
      newExpanded.add(topic);
    }
    setExpandedTopics(newExpanded);
  };

  if (!topicsSummary || !topicsSummary.topics || topicsSummary.topics.length === 0) {
    return (
      <div className="flex items-center justify-center h-[400px] bg-gray-50 dark:bg-gray-800/50 rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-700">
        <div className="text-center">
          <Tag className="w-16 h-16 mx-auto mb-4 text-gray-400 dark:text-gray-600" />
          <p className="text-lg font-medium text-gray-600 dark:text-gray-400">
            No topics data available
          </p>
        </div>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="w-full space-y-4"
    >
      {/* Header with Topic Count */}
      <div className="flex items-center justify-end mb-6">
        <div className="px-4 py-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
          <p className="text-sm font-semibold text-blue-700 dark:text-blue-300">
            {topicsSummary.total_topics} Topics Identified
          </p>
        </div>
      </div>

      {/* Topics List */}
      <div className="space-y-3">
        {topicsSummary.topics.map((topicData, index) => {
          const isExpanded = expandedTopics.has(topicData.topic);
          
          return (
            <motion.div
              key={topicData.topic}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: index * 0.05 }}
              className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden"
            >
              {/* Topic Header - Clickable */}
              <button
                onClick={() => toggleTopic(topicData.topic)}
                className="w-full p-4 flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
              >
                <div className="flex items-center gap-3 flex-1">
                  {isExpanded ? (
                    <ChevronDown className="w-5 h-5 text-gray-500 dark:text-gray-400 flex-shrink-0" />
                  ) : (
                    <ChevronRight className="w-5 h-5 text-gray-500 dark:text-gray-400 flex-shrink-0" />
                  )}
                  <h4 className="text-left font-semibold text-gray-900 dark:text-gray-100">
                    {topicData.topic}
                  </h4>
                </div>
                <div className="flex items-center gap-2">
                  <span className="px-3 py-1 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 text-sm rounded-full font-medium">
                    {topicData.paper_ids.length} papers
                  </span>
                </div>
              </button>

              {/* Expanded Content - Papers */}
              <AnimatePresence>
                {isExpanded && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.3 }}
                    className="border-t border-gray-200 dark:border-gray-700"
                  >
                    <div className="p-4 space-y-3 bg-gray-50 dark:bg-gray-900/50">
                      {topicData.paper_ids.length === 0 ? (
                        <p className="text-sm text-gray-500 dark:text-gray-400 italic">
                          No papers found for this topic
                        </p>
                      ) : (
                        topicData.paper_ids.map((paperId, paperIndex) => {
                          const paperDetails = papersMap.get(paperId);
                          
                          return (
                            <motion.div
                              key={paperId}
                              initial={{ opacity: 0, x: -10 }}
                              animate={{ opacity: 1, x: 0 }}
                              transition={{ duration: 0.2, delay: paperIndex * 0.05 }}
                              className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4 hover:shadow-md transition-shadow"
                            >
                              {paperDetails ? (
                                <div className="space-y-3">
                                  {/* Title with PDF Link */}
                                  <div className="flex items-start gap-2">
                                    <BookOpen className="w-4 h-4 mt-1 text-blue-600 dark:text-blue-400 flex-shrink-0" />
                                    <div className="flex-1">
                                      <div className="flex items-start justify-between gap-2">
                                        <h5 className="font-semibold text-gray-900 dark:text-gray-100 leading-tight">
                                          {paperDetails.title}
                                        </h5>
                                        {paperDetails.pdf_url && (
                                          <a
                                            href={paperDetails.pdf_url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="flex-shrink-0 p-1 text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded transition-colors"
                                            title="View PDF"
                                          >
                                            <ExternalLink className="w-4 h-4" />
                                          </a>
                                        )}
                                      </div>
                                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                                        ID: {paperId}
                                      </p>
                                    </div>
                                  </div>

                                  {/* Authors */}
                                  {paperDetails.authors && paperDetails.authors.length > 0 && (
                                    <div className="flex items-start gap-2">
                                      <UsersIcon className="w-4 h-4 mt-0.5 text-gray-500 dark:text-gray-400 flex-shrink-0" />
                                      <p className="text-sm text-gray-600 dark:text-gray-400">
                                        {paperDetails.authors.slice(0, 3).join(", ")}
                                        {paperDetails.authors.length > 3 && ` +${paperDetails.authors.length - 3} more`}
                                      </p>
                                    </div>
                                  )}

                                  {/* Date */}
                                  {paperDetails.date && (
                                    <div className="flex items-center gap-2">
                                      <Calendar className="w-4 h-4 text-gray-500 dark:text-gray-400 flex-shrink-0" />
                                      <p className="text-sm text-gray-600 dark:text-gray-400">
                                        {new Date(paperDetails.date).toLocaleDateString('en-US', {
                                          year: 'numeric',
                                          month: 'long',
                                          day: 'numeric'
                                        })}
                                      </p>
                                    </div>
                                  )}

                                  {/* Keywords */}
                                  {paperDetails.keywords && paperDetails.keywords.length > 0 && (
                                    <div className="flex flex-wrap gap-1.5">
                                      {paperDetails.keywords.slice(0, 5).map((keyword, kIndex) => (
                                        <span
                                          key={kIndex}
                                          className="px-2 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 text-xs rounded-full font-medium"
                                        >
                                          {keyword}
                                        </span>
                                      ))}
                                      {paperDetails.keywords.length > 5 && (
                                        <span className="px-2 py-0.5 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 text-xs rounded-full font-medium">
                                          +{paperDetails.keywords.length - 5}
                                        </span>
                                      )}
                                    </div>
                                  )}

                                  {/* Abstract Preview */}
                                  {paperDetails.abstract && (
                                    <div className="pt-2 border-t border-gray-200 dark:border-gray-700">
                                      <p className="text-sm text-gray-600 dark:text-gray-400 line-clamp-3">
                                        {paperDetails.abstract}
                                      </p>
                                    </div>
                                  )}
                                </div>
                              ) : (
                                <div className="flex items-center gap-2">
                                  <BookOpen className="w-4 h-4 text-gray-400 dark:text-gray-600" />
                                  <p className="text-sm text-gray-500 dark:text-gray-400">
                                    Paper ID: {paperId} <span className="italic">(details not available)</span>
                                  </p>
                                </div>
                              )}
                            </motion.div>
                          );
                        })
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          );
        })}
      </div>

      {/* Footer Stats */}
      <div className="mt-6 p-4 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700">
        <p className="text-sm text-gray-600 dark:text-gray-400 text-center">
          Total of <span className="font-semibold text-gray-900 dark:text-gray-100">{topicsSummary.total_topics} topics</span> covering{" "}
          <span className="font-semibold text-gray-900 dark:text-gray-100">
            {topicsSummary.topics.reduce((sum, topic) => sum + topic.paper_ids.length, 0)} papers
          </span>
        </p>
      </div>
    </motion.div>
  );
}
