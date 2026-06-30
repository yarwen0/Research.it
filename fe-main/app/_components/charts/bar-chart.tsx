"use client";
import { BarChart } from "@mui/x-charts/BarChart";
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
}

export default function BarChartVisualization({ chart }: { chart: ChartData }) {
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
  const isVertical = chart.config.layout === "vertical";
  const isStacked = chart.config.stacked === true;
  
  // Prepare data for MUI BarChart
  // Always use "label" as the dataKey for x-axis (prioritize label over id)
  const dataKey = "label";
  
  // Flatten nested metadata in dataPoints
  const flattenedData = chart.dataPoints.map((item: any) => {
    const flattened: any = { ...item };
    
    // If there's a metadata object, flatten it
    if (item.metadata && typeof item.metadata === 'object') {
      Object.entries(item.metadata).forEach(([key, value]) => {
        // Only flatten non-object values to avoid deep nesting issues
        if (typeof value !== 'object' || value === null) {
          flattened[key] = value;
        }
      });
    }
    
    return flattened;
  });
  
  // Validate that all data points have the required dataKey
  const validData = flattenedData.filter((item: any) => {
    return item[dataKey] !== undefined && item[dataKey] !== null;
  });
  
  if (validData.length === 0) {
    return (
      <div className="w-full h-[500px] flex items-center justify-center">
        <p className="text-gray-600 dark:text-gray-400">
          No valid data available for this chart
        </p>
      </div>
    );
  }
  
  // For stacked charts, use all series; for regular charts, use the first series
  const seriesConfig = chart.series && chart.series.length > 0
    ? chart.series.map((s) => {
        // Handle both dataKey and valueKey properties
        let key = s.dataKey || s.valueKey || "value";
        
        // Handle nested paths like "metadata.uniqueMethods"
        if (key.includes('.')) {
          const parts = key.split('.');
          key = parts[parts.length - 1]; // Use the last part as the key
        }
        
        return {
          dataKey: key,
          label: s.label,
          color: s.color || "#3b82f6",
          stack: isStacked ? (s.stack || (s.stacked ? "total" : undefined)) : undefined,
        };
      })
    : [
        {
          dataKey: "value",
          label: "Count",
          color: "#3b82f6",
          stack: undefined,
        },
      ];

  // Truncate long labels for better display
  const processedData = validData.map((item: any) => {
    const label = item[dataKey];
    if (typeof label === "string" && label.length > 50) {
      return {
        ...item,
        [dataKey]: label.substring(0, 50) + "...",
        fullLabel: label,
      };
    }
    return item;
  });
  
  return (
    <div className="w-full h-[500px]">
      {isVertical ? (
        // Horizontal layout (bars go horizontally, y-axis has categories)
        <BarChart
          dataset={processedData}
          yAxis={[{
            scaleType: "band",
            dataKey: dataKey,
            label: chart.config.xAxisLabel || undefined,
            labelStyle: {
              fill: isDark ? '#e5e7eb' : '#374151',
            },
            tickLabelStyle: {
              fill: isDark ? '#9ca3af' : '#6b7280',
            },
          }]}
          xAxis={[{
            label: chart.config.yAxisLabel || undefined,
            labelStyle: {
              fill: isDark ? '#e5e7eb' : '#374151',
            },
            tickLabelStyle: {
              fill: isDark ? '#9ca3af' : '#6b7280',
            },
          }]}
          series={seriesConfig}
          layout="horizontal"
          margin={{ top: 20, right: 30, bottom: 60, left: 200 }}
          sx={{
            '& .MuiChartsAxis-line': {
              stroke: isDark ? '#4b5563' : '#d1d5db',
            },
            '& .MuiChartsAxis-tick': {
              stroke: isDark ? '#4b5563' : '#d1d5db',
            },
            '& .MuiChartsGrid-line': {
              stroke: isDark ? '#374151' : '#e5e7eb',
            },
            '& .MuiChartsLegend-root text': {
              fill: isDark ? '#e5e7eb' : '#374151',
            },
            '& .MuiChartsLegend-mark': {
              rx: 2,
            },
          }}
        />
      ) : (
        // Vertical layout (bars go vertically, x-axis has categories)
        <BarChart
          dataset={processedData}
          xAxis={[{
            scaleType: "band",
            dataKey: dataKey,
            label: chart.config.xAxisLabel || undefined,
            labelStyle: {
              fill: isDark ? '#e5e7eb' : '#374151',
            },
            tickLabelStyle: {
              fill: isDark ? '#9ca3af' : '#6b7280',
            },
          }]}
          yAxis={[{
            label: chart.config.yAxisLabel || undefined,
            labelStyle: {
              fill: isDark ? '#e5e7eb' : '#374151',
            },
            tickLabelStyle: {
              fill: isDark ? '#9ca3af' : '#6b7280',
            },
          }]}
          series={seriesConfig}
          layout="vertical"
          margin={{ top: 20, right: 30, bottom: 120, left: 60 }}
          sx={{
            '& .MuiChartsAxis-line': {
              stroke: isDark ? '#4b5563' : '#d1d5db',
            },
            '& .MuiChartsAxis-tick': {
              stroke: isDark ? '#4b5563' : '#d1d5db',
            },
            '& .MuiChartsGrid-line': {
              stroke: isDark ? '#374151' : '#e5e7eb',
            },
            '& .MuiChartsLegend-root text': {
              fill: isDark ? '#e5e7eb' : '#374151',
            },
            '& .MuiChartsLegend-mark': {
              rx: 2,
            },
          }}
        />
      )}
    </div>
  );
}
