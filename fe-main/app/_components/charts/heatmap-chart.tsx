"use client";
import { ResponsiveHeatMap } from '@nivo/heatmap';
import { useMemo } from 'react';

interface HeatmapDataPoint {
  x: number;
  y: number;
  value: number;
}

interface HeatmapChart {
  config: {
    type: "heatmap";
    title: string;
    description: string;
    xAxisLabel?: string;
    yAxisLabel?: string;
  };
  dataPoints: HeatmapDataPoint[];
  series: Array<{
    name: string;
    data: Array<[number, number, number]>; // [x, y, value]
  }>;
  heatmap: {
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

interface HeatmapChartVisualizationProps {
  chart: HeatmapChart;
}

export default function HeatmapChartVisualization({ chart }: HeatmapChartVisualizationProps) {
  // Transform backend data to Nivo format
  const nivoData = useMemo(() => {
    const yAxisData = chart.heatmap.yAxis[0]?.data || [];
    const xAxisData = chart.heatmap.xAxis[0]?.data || [];
    const seriesData = chart.series[0]?.data || [];

    return yAxisData.map((topic, yIdx) => ({
      id: topic,
      data: xAxisData.map((method, xIdx) => {
        const dataPoint = seriesData.find(
          ([x, y]) => x === xIdx && y === yIdx
        );
        return {
          x: method,
          y: dataPoint ? dataPoint[2] : 0
        };
      })
    }));
  }, [chart]);

  return (
    <div className="w-full h-[600px]">
      <ResponsiveHeatMap
        data={nivoData}
        margin={{ top: 60, right: 90, bottom: 60, left: 90 }}
        valueFormat=">-.0f"
        axisTop={{
          tickSize: 5,
          tickPadding: 5,
          tickRotation: -45,
          legend: chart.config.xAxisLabel || '',
          legendOffset: 46
        }}
        axisLeft={{
          tickSize: 5,
          tickPadding: 5,
          tickRotation: 0,
          legend: chart.config.yAxisLabel || 'Topics',
          legendPosition: 'middle',
          legendOffset: -72
        }}
        colors={{
          type: 'sequential',
          scheme: 'blues'
        }}
        emptyColor="#555555"
        legends={[
          {
            anchor: 'bottom',
            translateX: 0,
            translateY: 30,
            length: 400,
            thickness: 8,
            direction: 'row',
            tickPosition: 'after',
            tickSize: 3,
            tickSpacing: 4,
            tickOverlap: false,
            title: 'Usage Frequency →',
            titleAlign: 'start',
            titleOffset: 4
          }
        ]}
      />
    </div>
  );
}
