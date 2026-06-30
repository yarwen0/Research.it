"use client";
import { LineChart } from "@mui/x-charts/LineChart";
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

export default function LineChartVisualization({ chart }: { chart: ChartData }) {
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
  
  // Prepare data for MUI LineChart
  // Always use "label" as the x-axis key (prioritize label over id)
  const xAxisKey = "label";
  
  // Flatten nested data paths (e.g., "metadata.uniqueMethods" -> direct key)
  const flattenedData = chart.dataPoints.map((point: any) => {
    const flattened: any = { ...point };
    
    // If there's a metadata object, flatten it
    if (point.metadata && typeof point.metadata === 'object') {
      Object.entries(point.metadata).forEach(([key, value]) => {
        flattened[key] = value;
      });
    }
    
    return flattened;
  });
  
  // Process series to handle both dataKey and valueKey, and flatten nested paths
  const series = chart.series && chart.series.length > 0 
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
        };
      })
    : [{ dataKey: "value", label: "Value", color: "#3b82f6" }];

  return (
    <div className="w-full h-[500px]">
      <LineChart
        dataset={flattenedData}
        xAxis={[
          {
            scaleType: "point",
            dataKey: xAxisKey,
            label: chart.config.xAxisLabel || undefined,
            valueFormatter: (value: any) => String(value),
            labelStyle: {
              fill: isDark ? '#e5e7eb' : '#374151',
            },
            tickLabelStyle: {
              fill: isDark ? '#9ca3af' : '#6b7280',
            },
          },
        ]}
        yAxis={[
          {
            label: chart.config.yAxisLabel || undefined,
            labelStyle: {
              fill: isDark ? '#e5e7eb' : '#374151',
            },
            tickLabelStyle: {
              fill: isDark ? '#9ca3af' : '#6b7280',
            },
          },
        ]}
        series={series.map((s) => ({
          dataKey: s.dataKey,
          label: s.label,
          color: s.color,
          showMark: true,
          curve: "linear",
        }))}
        margin={{ top: 20, right: 30, bottom: 80, left: 60 }}
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
        }}
      />
    </div>
  );
}
