"use client";
import { PieChart } from "@mui/x-charts/PieChart";
import { useEffect, useState } from "react";
import { ExternalLink } from "lucide-react";

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

export default function PieChartVisualization({ chart }: { chart: ChartData }) {
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
  
  // Prepare data for MUI PieChart - handle both dataKey and valueKey
  const valueKey = chart.series?.[0]?.dataKey || chart.series?.[0]?.valueKey || "value";
  
  // Format data for MUI PieChart
  const pieData = chart.dataPoints.map((item: any, index: number) => {
    // Try to get the label from multiple possible fields
    let label = item.dataset || item.label || item.name || item.method || item.topic || `Item ${item.id || index}`;
    
    // Truncate long labels
    if (typeof label === "string" && label.length > 30) {
      label = label.substring(0, 30) + "...";
    }
    
    // Get value from the specified valueKey or common value fields
    const value = item[valueKey] || item.count || item.value || 0;
    
    return {
      id: item.id ?? item.dataset ?? label ?? index,
      value: value,
      label: label,
    };
  });

  return (
    <div className="w-full flex flex-col items-center justify-center">
      <div className="h-[300px] w-full">
        <PieChart
          series={[
            {
              data: pieData,
              highlightScope: { fade: "global", highlight: "item" },
              faded: { innerRadius: 30, additionalRadius: -30, color: "gray" },
              arcLabel: (item) => `${item.value}`,
              arcLabelMinAngle: 20,
            },
          ]}
          margin={{ top: 20, right: 20, bottom: 20, left: 20 }}
          sx={{
            '& .MuiChartsLegend-root': {
              display: 'none',
            },
            '& .MuiPieArc-root text': {
              fill: '#ffffff',
              fontWeight: 'bold',
              fontSize: '12px',
            },
            '& circle': {
              transformOrigin: 'center',
            },
          }}
        />
      </div>
      
      {/* Custom Legend with Google Search Links - Below Chart */}
      <div className="w-full space-y-1.5 max-h-[200px] overflow-y-auto mt-4">
        {pieData.map((item, index) => (
          <div 
            key={item.id}
            className="flex items-center gap-2 group px-2 py-1 hover:bg-gray-50 dark:hover:bg-gray-700/50 rounded"
          >
            <div 
              className="w-3 h-3 rounded flex-shrink-0" 
              style={{ backgroundColor: `hsl(${(index * 360) / pieData.length}, 70%, 50%)` }}
            />
            <div className="flex-1 min-w-0">
              <span className="text-xs text-gray-700 dark:text-gray-300 break-words">
                {item.label}
              </span>
              <span className="text-xs text-gray-500 dark:text-gray-400 ml-1">
                ({item.value})
              </span>
            </div>
            <a
              href={`https://www.google.com/search?q=${encodeURIComponent(item.label + " dataset")}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary hover:text-primary/80 transition-colors opacity-0 group-hover:opacity-100 flex-shrink-0"
              title="Search on Google"
            >
              <ExternalLink className="w-3 h-3" />
            </a>
          </div>
        ))}
      </div>
    </div>
  );
}
