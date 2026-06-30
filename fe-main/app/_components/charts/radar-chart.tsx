"use client";
import { RadarChart } from "@mui/x-charts/RadarChart";
import { useEffect, useState } from "react";

interface ChartSeries {
  id?: string;
  dataKey?: string;
  label: string;
  color?: string;
  valueKey?: string;
  valueFormatter?: string;
  stack?: string;
  stacked?: boolean;
  data?: number[]; // For radar charts with pre-computed data arrays
  fullTopic?: string; // Full topic name for radar charts
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
  };
  dataPoints: any[];
  series: ChartSeries[];
  radar?: {
    metrics: string[];
    max: number;
  };
}

export default function RadarChartVisualization({ chart }: { chart: ChartData }) {
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    // Check if dark mode is enabled
    const checkDarkMode = () => {
      setIsDark(document.documentElement.classList.contains('dark'));
    };
    
    checkDarkMode();
    
    // Watch for changes to dark mode
    const observer = new MutationObserver(checkDarkMode);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    });
    
    return () => observer.disconnect();
  }, []);

  // Validate data
  if (!chart.series || chart.series.length === 0 || !chart.dataPoints || chart.dataPoints.length === 0) {
    return (
      <div className="w-full h-[500px] flex items-center justify-center">
        <p className="text-gray-600 dark:text-gray-400">
          No valid data available for this chart
        </p>
      </div>
    );
  }

  // Default colors for series
  const defaultColors = [
    "#3b82f6", // blue
    "#10b981", // green
    "#f59e0b", // amber
    "#ef4444", // red
    "#8b5cf6", // purple
    "#ec4899", // pink
    "#06b6d4", // cyan
    "#f97316", // orange
  ];

  // Extract category labels from dataPoints
  const categories = chart.dataPoints.map((point: any) => point.label || point.fullName || "");

  // Prepare series data for MUI RadarChart
  // Each series has pre-computed data array matching the categories
  const seriesConfig = chart.series.map((s, index) => ({
    data: s.data || [], // Use the pre-computed data array
    label: s.label || s.fullTopic || `Series ${index + 1}`,
    color: s.color || defaultColors[index % defaultColors.length],
  }));

  // Calculate max value for the radar scale
  const maxValue = chart.radar?.max || Math.max(
    ...chart.series.flatMap(s => s.data || []).filter(v => typeof v === 'number')
  );

  return (
    <div className="w-full h-[600px] flex flex-col gap-4">
      {/* Info text */}
      <div className="text-sm text-gray-600 dark:text-gray-400 text-center">
        Showing method distribution across categories for each research topic
      </div>
      
      {/* Chart */}
      <div className="flex-1 flex items-center justify-center bg-white dark:bg-slate-900 rounded-lg">
        <RadarChart
          series={seriesConfig.map(s => ({
            data: s.data,
            label: s.label,
            color: s.color,
          }))}
          radar={{
            metrics: categories,
            max: maxValue > 0 ? Math.ceil(maxValue * 1.1) : 20,
          }}
          width={700}
          height={500}
          margin={{ top: 70, right: 150, bottom: 70, left: 150 }}
          sx={{
            "& .MuiChartsAxis-line": {
              stroke: isDark ? "#6b7280" : "#d1d5db",
            },
            "& .MuiChartsAxis-tick": {
              stroke: isDark ? "#6b7280" : "#d1d5db",
            },
            "& .MuiChartsAxis-tickLabel": {
              fill: isDark ? "#d1d5db" : "#6b7280",
              fontSize: "11px",
            },
            "& .MuiChartsLegend-series text": {
              fill: isDark ? "#f3f4f6" : "#374151",
              fontSize: "12px !important",
            },
            "& .MuiChartsRadar-polygon": {
              fill: isDark ? "rgba(51, 65, 85, 0.3)" : "rgba(229, 231, 235, 0.3)",
              stroke: isDark ? "#475569" : "#e5e7eb",
            },
            "& .MuiChartsRadar-plot": {
              strokeWidth: 2,
            },
          }}
        />
      </div>
      
      {/* Additional info about categories */}
      <div className="text-xs text-gray-500 dark:text-gray-400 text-center">
        {chart.dataPoints.length} method categories • {chart.series.length} research topics
      </div>
    </div>
  );
}
