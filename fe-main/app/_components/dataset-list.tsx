"use client";
import { motion, AnimatePresence } from "framer-motion";
import { Database, ChevronDown, ChevronRight, ExternalLink } from "lucide-react";
import PieChartVisualization from "./charts/pie-chart";

interface DatasetPaper {
  paper_id: string;
  title: string;
  original_name_used: string;
}

interface Dataset {
  normalized_id: string;
  original_names: string[];
  paper_count: number;
  papers: DatasetPaper[];
}

interface ChartSeries {
  id?: string;
  dataKey?: string;
  label: string;
  color?: string;
  valueKey?: string;
  valueFormatter?: string;
  stack?: string;
  stacked?: boolean;
}

interface ChartData {
  config: {
    type: "bar" | "pie" | "line";
    title: string;
    description: string;
    xAxisLabel?: string | null;
    yAxisLabel?: string | null;
    layout?: "horizontal" | "vertical" | null;
    stacked?: boolean;
  };
  dataPoints: any[];
  series: ChartSeries[];
}

interface DatasetListProps {
  datasets: Dataset[];
  selectedIndex: number;
  onSelectDataset: (index: number) => void;
  expandedDetails?: React.ReactNode;
  totalDatasets?: number;
  pieChart?: ChartData;
}

export default function DatasetList({ 
  datasets, 
  selectedIndex, 
  onSelectDataset, 
  expandedDetails,
  totalDatasets,
  pieChart
}: DatasetListProps) {
  return (
    <div className="overflow-y-auto space-y-4">
      {/* Summary Card */}
      {totalDatasets && (
        <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-4 border border-green-200 dark:border-green-800">
          <div className="flex items-center gap-2 mb-2">
            <Database className="w-5 h-5 text-green-600 dark:text-green-400" />
            <h3 className="text-base font-bold text-gray-900 dark:text-gray-100">
              Dataset Overview
            </h3>
          </div>
          <p className="text-sm text-gray-700 dark:text-gray-300">
            Found <span className="font-bold text-green-600 dark:text-green-400">{totalDatasets}</span> unique datasets across the research papers
          </p>
        </div>
      )}

      {/* Pie Chart */}
      {pieChart && (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.3 }}
          className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm p-4"
        >
          <div className="mb-3">
            <h4 className="text-sm font-bold text-gray-900 dark:text-gray-100 mb-1">
              {pieChart.config.title}
            </h4>
            <p className="text-xs text-gray-600 dark:text-gray-400">
              {pieChart.config.description}
            </p>
          </div>
          <PieChartVisualization chart={pieChart} />
        </motion.div>
      )}

      {/* Dataset List Header */}
      <div className="flex items-center justify-between px-1">
        <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
          All Datasets ({datasets.length})
        </h4>
      </div>

      {/* Dataset List with Inline Expansion */}
      {datasets.map((dataset, index) => {
        const isSelected = selectedIndex === index;
        
        return (
          <div key={index}>
            <motion.button
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.3, delay: index * 0.05 }}
              onClick={() => onSelectDataset(isSelected ? -1 : index)}
              className={`w-full p-3 text-left rounded-lg border transition-all duration-200 ${
                isSelected
                  ? "bg-green-50 dark:bg-green-900/20 border-green-500 dark:border-green-500 shadow-md"
                  : "bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 hover:border-green-300 dark:hover:border-green-700 hover:shadow-sm"
              }`}
            >
              <div className="flex items-start gap-2">
                {isSelected ? (
                  <ChevronDown className="w-4 h-4 mt-1 flex-shrink-0 text-green-600 dark:text-green-400" />
                ) : (
                  <ChevronRight className="w-4 h-4 mt-1 flex-shrink-0 text-gray-500 dark:text-gray-400" />
                )}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-2">
                    <h3
                      className={`font-semibold text-sm leading-tight flex-1 ${
                        isSelected
                          ? "text-green-900 dark:text-green-100"
                          : "text-gray-900 dark:text-gray-100"
                      }`}
                    >
                      {dataset.normalized_id}
                    </h3>
                    <span
                      className={`px-2 py-0.5 text-xs rounded-full font-medium ${
                        isSelected
                          ? "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300"
                          : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                      }`}
                    >
                      {dataset.paper_count} papers
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {dataset.original_names.slice(0, 2).map((name, nameIdx) => (
                      <span
                        key={nameIdx}
                        className={`px-2 py-0.5 text-xs rounded-full font-medium ${
                          isSelected
                            ? "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300"
                            : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"
                        }`}
                      >
                        {name}
                      </span>
                    ))}
                    {dataset.original_names.length > 2 && (
                      <span className="px-2 py-0.5 text-xs rounded-full font-medium bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                        +{dataset.original_names.length - 2}
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
