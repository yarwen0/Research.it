"use client";
import { motion } from "framer-motion";
import { BarChart3, PieChart as PieChartIcon, TrendingUp, Tag, Radar } from "lucide-react";
import { useState, useEffect, useMemo } from "react";
import BarChartVisualization from "./charts/bar-chart";
import PieChartVisualization from "./charts/pie-chart";
import LineChartVisualization from "./charts/line-chart";
import RadarChartVisualization from "./charts/radar-chart";
import WordcloudChartVisualization from "./charts/wordcloud-chart";
import SankeyChartVisualization from "./charts/sankey-chart";
import HeatmapChartVisualization from "./charts/heatmap-chart";
import TopicsSummary from "./topics-summary";

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
    type: "bar" | "pie" | "line" | "radar" | "wordcloud" | "sankey" | "heatmap";
    title: string;
    description: string;
    xAxisLabel?: string | null;
    yAxisLabel?: string | null;
    layout?: "horizontal" | "vertical" | null;
    stacked?: boolean;
    fromKey?: string;
    toKey?: string;
    sizeKey?: string;
  };
  dataPoints: any[];
  series: ChartSeries[];
  wordcloud?: {
    minFontSize: number;
    maxFontSize: number;
    rotationAngles: number[];
  };
  sankey?: {
    totalLinks: number;
    nodeAlignment: string;
    uniqueNodes: number;
  };
  heatmap?: {
    xAxis: Array<{
      type: string;
      data: string[];
    }>;
    yAxis: Array<{
      type: string;
      data: string[];
    }>;
    minValue: number;
    maxValue: number;
  };
}

interface TopicsSummary {
  total_topics: number;
  topics: {
    topic: string;
    paper_ids: string[];
  }[];
}

interface MetricsChartProps {
  metrics: {
    publication_timeline?: ChartData;
    method_frequency?: ChartData;
    dataset_distribution?: ChartData;
    topic_coverage?: ChartData;
    assumptions_analysis?: ChartData;
    limitations_analysis?: ChartData;
    methods_by_topic?: ChartData;
    research_evolution?: ChartData;
    collaboration_metrics?: ChartData;
    future_work_themes?: ChartData;
    assumptions_wordcloud?: ChartData;
    limitations_wordcloud?: ChartData;
    research_flow_sankey?: ChartData;
    methods_topics_heatmap?: ChartData;
    topics_summary?: TopicsSummary;
  };
  processedPapers?: any[]; // Pass the current response's processed_papers
}

const getChartIcon = (type: string) => {
  switch (type) {
    case "pie":
      return PieChartIcon;
    case "line":
      return TrendingUp;
    case "radar":
      return Radar;
    case "topics":
      return Tag;
    case "wordcloud":
      return Tag;
    case "sankey":
      return TrendingUp;
    case "heatmap":
      return BarChart3;
    default:
      return BarChart3;
  }
};

export default function MetricsChart({ metrics, processedPapers = [] }: MetricsChartProps) {
  const [selectedChartKey, setSelectedChartKey] = useState<string>("");

  // Check if topics_summary exists and add it as a special entry
  const topicsSummary = metrics?.topics_summary;
  const hasTopicsSummary = topicsSummary && topicsSummary.topics && topicsSummary.topics.length > 0;

  // Memoize the charts array to prevent recalculation on every render
  const charts = useMemo(() => {
    if (!metrics) return [];
    
    // Debug logging
    console.log("=== METRICS DEBUG ===");
    console.log("All metrics keys:", Object.keys(metrics));
    
    const processedCharts = Object.entries(metrics || {})
      .filter(([key, value]) => {
        // Skip metadata and topics_summary (handled separately)
        if (key === 'metadata' || key === 'topics_summary') return false;
        
        // Filter out the old topic_coverage chart since we're replacing it
        if (key === 'topic_coverage') {
          console.log(`⚠️ Skipping legacy topic_coverage chart`);
          return false;
        }
        
        if (!value || typeof value !== 'object') {
          console.log(`❌ ${key}: Invalid - not an object`);
          return false;
        }
        const chartData = value as ChartData;
        
        console.log(`\n📊 Chart: ${key}`);
        console.log("  Config:", JSON.stringify(chartData.config, null, 2));
        console.log("  Data Points Count:", chartData.dataPoints?.length || 0);
        console.log("  Data Points Sample:", JSON.stringify(chartData.dataPoints?.slice(0, 2), null, 2));
        console.log("  Series:", JSON.stringify(chartData.series, null, 2));
        
        const specialChartTypes = ['wordcloud', 'sankey', 'heatmap'];
        const requiresSeries = !specialChartTypes.includes(chartData.config?.type);
        
        const isValid = chartData.config && 
                        Array.isArray(chartData.dataPoints) && 
                        chartData.dataPoints.length > 0 &&
                        (!requiresSeries || (Array.isArray(chartData.series) && chartData.series.length > 0));
        
        console.log(`  Valid: ${isValid ? '✅' : '❌'}`);
        
        return isValid;
      })
      .map(([key, value]) => ({ key, ...value as ChartData }));
    
    console.log("\n=== END METRICS DEBUG ===\n");
    return processedCharts;
  }, [metrics]);

  // Set initial selected chart when charts are loaded
  useEffect(() => {
    if (!selectedChartKey) {
      if (hasTopicsSummary) {
        setSelectedChartKey("topics_summary");
      } else if (charts.length > 0) {
        setSelectedChartKey(charts[0].key);
      }
    }
  }, [charts, selectedChartKey, hasTopicsSummary]);

  // Find the selected chart
  const currentChart = useMemo(() => {
    if (selectedChartKey === "topics_summary") return null;
    return charts.find(chart => chart.key === selectedChartKey) || charts[0];
  }, [charts, selectedChartKey]);

  const totalItems = charts.length + (hasTopicsSummary ? 1 : 0);

  if (totalItems === 0) {
    return (
      <div className="flex items-center justify-center h-[400px] bg-gray-50 dark:bg-gray-800/50 rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-700">
        <div className="text-center">
          <BarChart3 className="w-16 h-16 mx-auto mb-4 text-gray-400 dark:text-gray-600" />
          <p className="text-lg font-medium text-gray-600 dark:text-gray-400">
            No metrics data available
          </p>
        </div>
      </div>
    );
  }

  // Handle topics_summary view separately
  const isTopicsSummaryView = selectedChartKey === "topics_summary";

  if (!isTopicsSummaryView && (!currentChart?.config || !currentChart?.dataPoints || !currentChart?.series)) {
    return (
      <div className="flex items-center justify-center h-[400px] bg-gray-50 dark:bg-gray-800/50 rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-700">
        <div className="text-center">
          <BarChart3 className="w-16 h-16 mx-auto mb-4 text-gray-400 dark:text-gray-600" />
          <p className="text-lg font-medium text-gray-600 dark:text-gray-400">
            Invalid chart configuration
          </p>
        </div>
      </div>
    );
  }
  
  const Icon = isTopicsSummaryView ? Tag : getChartIcon(currentChart?.config?.type || "bar");

  // Format chart key for display
  const formatChartLabel = (key: string) => {
    return key
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  const renderChart = (chart: ChartData) => {
    switch (chart.config.type) {
      case "bar":
        return <BarChartVisualization chart={chart as any} />;
      case "pie":
        return <PieChartVisualization chart={chart as any} />;
      case "line":
        return <LineChartVisualization chart={chart as any} />;
      case "radar":
        return <RadarChartVisualization chart={chart} />;
      case "wordcloud":
        return <WordcloudChartVisualization chart={chart as any} />;
      case "sankey":
        return <SankeyChartVisualization chart={chart as any} />;
      case "heatmap":
        return <HeatmapChartVisualization chart={chart as any} />;
      default:
        return (
          <div className="flex items-center justify-center h-[400px]">
            <p className="text-gray-600 dark:text-gray-400">
              Unknown chart type: {chart.config.type}
            </p>
          </div>
        );
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="w-full"
    >
      {/* Header with Select Dropdown */}
      <div className="mb-6 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Icon className="w-6 h-6 text-blue-600 dark:text-blue-400" />
            <h3 className="text-xl font-bold text-gray-900 dark:text-gray-100">
              {isTopicsSummaryView ? "Research Topics Coverage" : currentChart?.config?.title || ""}
            </h3>
          </div>
          
          {/* Chart Selector */}
          <div className="flex items-center gap-2">
            <label 
              htmlFor="chart-select" 
              className="text-sm font-medium text-gray-700 dark:text-gray-300"
            >
              View:
            </label>
            <select
              id="chart-select"
              value={selectedChartKey}
              onChange={(e) => setSelectedChartKey(e.target.value)}
              className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-blue-400 transition-colors cursor-pointer"
            >
              {hasTopicsSummary && (
                <option value="topics_summary">Topics Coverage</option>
              )}
              {charts.map((chart) => (
                <option key={chart.key} value={chart.key}>
                  {formatChartLabel(chart.key)}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Chart Description */}
        {!isTopicsSummaryView && currentChart && (
          <p className="text-center text-gray-600 dark:text-gray-400">
            {currentChart.config.description}
          </p>
        )}
      </div>

      {/* Chart Content */}
      <motion.div
        key={selectedChartKey}
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.2 }}
      >
        {isTopicsSummaryView ? (
          <TopicsSummary topicsSummary={topicsSummary!} processedPapers={processedPapers} />
        ) : currentChart ? (
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm p-6">
            {renderChart(currentChart)}
          </div>
        ) : null}
      </motion.div>

      {/* Chart Counter */}
      <div className="flex justify-center mt-4">
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Viewing{" "}
          {isTopicsSummaryView 
            ? 1 
            : (hasTopicsSummary ? 1 : 0) + charts.findIndex(c => c.key === selectedChartKey) + 1
          } of {totalItems} views
        </p>
      </div>
    </motion.div>
  );
}
