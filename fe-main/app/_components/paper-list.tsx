"use client";
import { motion, AnimatePresence } from "framer-motion";
import { BookOpen, ChevronDown, ChevronRight, Tag, FileText } from "lucide-react";

interface ResearchPaper {
  title: string;
  keywords: string[];
  abstract: string;
}

interface PaperListProps {
  papers: ResearchPaper[];
  selectedIndex: number;
  onSelectPaper: (index: number) => void;
  expandedDetails?: React.ReactNode;
}

export default function PaperList({ papers, selectedIndex, onSelectPaper, expandedDetails }: PaperListProps) {
  return (
    <div className="overflow-y-auto space-y-2">
      {papers.map((paper, index) => {
        const isSelected = selectedIndex === index;
        
        return (
          <div key={index}>
            <motion.button
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.3, delay: index * 0.05 }}
              onClick={() => onSelectPaper(isSelected ? -1 : index)}
              className={`w-full p-3 text-left rounded-lg border transition-all duration-200 ${
                isSelected
                  ? "bg-blue-50 dark:bg-blue-900/20 border-blue-500 dark:border-blue-500 shadow-md"
                  : "bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 hover:border-blue-300 dark:hover:border-blue-700 hover:shadow-sm"
              }`}
            >
              <div className="flex items-start gap-2">
                {isSelected ? (
                  <ChevronDown className="w-4 h-4 mt-1 flex-shrink-0 text-blue-600 dark:text-blue-400" />
                ) : (
                  <ChevronRight className="w-4 h-4 mt-1 flex-shrink-0 text-gray-500 dark:text-gray-400" />
                )}
                <div className="flex-1 min-w-0">
                  <h3
                    className={`font-semibold text-sm leading-tight mb-2 ${
                      isSelected
                        ? "text-blue-900 dark:text-blue-100"
                        : "text-gray-900 dark:text-gray-100"
                    }`}
                  >
                    {paper.title}
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {paper.keywords.slice(0, 3).map((keyword, keyIndex) => (
                      <span
                        key={keyIndex}
                        className={`px-2 py-0.5 text-xs rounded-full font-medium ${
                          isSelected
                            ? "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300"
                            : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                        }`}
                      >
                        {keyword}
                      </span>
                    ))}
                    {paper.keywords.length > 3 && (
                      <span className="px-2 py-0.5 text-xs rounded-full font-medium bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                        +{paper.keywords.length - 3}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </motion.button>

            {/* Expanded Details */}
            <AnimatePresence>
              {isSelected && expandedDetails && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.3 }}
                  className="overflow-hidden"
                >
                  {expandedDetails}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        );
      })}
    </div>
  );
}
