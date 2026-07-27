"use client";
import { Chart } from "react-google-charts";
import { useMemo } from 'react';

interface SankeyDataPoint {
  from: string;
  to: string;
  size: number;
  type: "topic_to_method" | "assumption_to_limitation";
}

interface SankeyChart {
  config: {
    type: "sankey";
    title: string;
    description: string;
    fromKey: string;
    toKey: string;
    sizeKey: string;
  };
  dataPoints: SankeyDataPoint[];
  series: Array<{
    type: "sankey";
    fromKey: string;
    toKey: string;
    sizeKey: string;
  }>;
  sankey: {
    totalLinks: number;
    nodeAlignment: string;
    uniqueNodes: number;
  };
}

interface SankeyChartVisualizationProps {
  chart: SankeyChart;
}

export default function SankeyChartVisualization({ chart }: SankeyChartVisualizationProps) {
  const { data, options } = useMemo(() => {
    if (!chart.dataPoints || chart.dataPoints.length === 0) {
      return { data: null, options: null };
    }

    const googleChartsData = [
      ['From', 'To', 'Weight'],
      ...chart.dataPoints.map(point => [
        point.from,
        point.to,
        point.size
      ])
    ];

    const chartOptions = {
      sankey: {
        node: {
          colors: ['#1976d2', '#2e7d32', '#d32f2f', '#f57c00', '#7b1fa2', '#0288d1', '#00897b'],
          nodePadding: 15,
          width: 20,
          label: {
            fontSize: 12,
            color: '#333',
            bold: true,
          },
        },
        link: {
          colorMode: 'gradient',
          colors: ['#cfe2f3', '#d9ead3', '#f4cccc', '#fce5cd', '#e1d5e7', '#cfe2f3', '#b2dfdb'],
        },
      },
    };

    return { data: googleChartsData, options: chartOptions };
  }, [chart]);

  if (!data || !chart.dataPoints || chart.dataPoints.length === 0) {
    return (
      <div className="w-full h-[600px] flex items-center justify-center bg-gray-50 dark:bg-gray-800/50 rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-700">
        <div className="text-center">
          <p className="text-lg font-medium text-gray-600 dark:text-gray-400">
            No data to display
          </p>
          <p className="text-sm text-gray-500 dark:text-gray-500 mt-2">
            {chart.sankey 
              ? `Expected ${chart.sankey.totalLinks} links and ${chart.sankey.uniqueNodes} nodes`
              : "Chart data is not available"}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-[600px]">
      <Chart
        chartType="Sankey"
        width="100%"
        height="600px"
        data={data}
        options={options}
      />
    </div>
  );
}
