"use client";
import dynamic from 'next/dynamic';
import { useMemo } from 'react';

// Dynamically import react-wordcloud to avoid SSR issues
const ReactWordcloud = dynamic(() => import('react-wordcloud'), { ssr: false });

interface WordcloudDataPoint {
  text: string;
  value: number;
  fullText: string;
  papers: string[];
  totalPapers: number;
}

interface WordcloudChart {
  config: {
    type: "wordcloud";
    title: string;
    description: string;
  };
  dataPoints: WordcloudDataPoint[];
  series: [];
  wordcloud: {
    minFontSize: number;
    maxFontSize: number;
    rotationAngles: number[];
  };
}

interface WordcloudChartVisualizationProps {
  chart: WordcloudChart;
}

export default function WordcloudChartVisualization({ chart }: WordcloudChartVisualizationProps) {
  const options = useMemo(() => ({
    fontSizes: [chart.wordcloud.minFontSize, chart.wordcloud.maxFontSize] as [number, number],
    rotations: chart.wordcloud.rotationAngles.length,
    rotationAngles: chart.wordcloud.rotationAngles.slice(0, 2) as [number, number],
    padding: 2,
    fontFamily: 'system-ui, -apple-system, sans-serif',
    enableTooltip: true,
    deterministic: true,
  }), [chart]);

  const callbacks = useMemo(() => ({
    getWordTooltip: (word: any) => {
      const dataPoint = chart.dataPoints.find(d => d.text === word.text);
      if (dataPoint) {
        return `${dataPoint.fullText}\nFrequency: ${dataPoint.value}\nPapers: ${dataPoint.totalPapers}`;
      }
      return `${word.text}: ${word.value}`;
    }
  }), [chart]);

  return (
    <div className="w-full h-[500px] flex items-center justify-center">
      <ReactWordcloud
        words={chart.dataPoints}
        options={options}
        callbacks={callbacks}
      />
    </div>
  );
}
