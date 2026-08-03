"use client";

import cloud from "d3-cloud";
import { useEffect, useMemo, useRef, useState } from "react";

/**
 * Word cloud built on d3-cloud directly.
 *
 * Replaces react-wordcloud, which is unmaintained and declares
 * `peerDependencies: react ^16.13.0` — it was already being tolerated at
 * React 18 and blocks React 19 outright. d3-cloud is the layout engine
 * react-wordcloud wrapped anyway, so this drops a wrapper rather than
 * swapping the algorithm.
 */

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

/** A word after layout, with the position d3-cloud assigned it. */
interface PlacedWord extends WordcloudDataPoint {
  x: number;
  y: number;
  rotate: number;
  size: number;
}

const HEIGHT = 500;

// Distinguishes words without encoding anything — size already carries
// frequency, so colour is decoration and must stay readable on both themes.
const PALETTE = [
  "#2563eb",
  "#7c3aed",
  "#db2777",
  "#ea580c",
  "#0891b2",
  "#16a34a",
];

export default function WordcloudChartVisualization({
  chart,
}: WordcloudChartVisualizationProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [placed, setPlaced] = useState<PlacedWord[]>([]);

  // d3-cloud needs concrete pixel dimensions, which are not known until the
  // container has been laid out.
  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const observer = new ResizeObserver(([entry]) => {
      setWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const { minFontSize, maxFontSize, rotationAngles } = chart.wordcloud;

  const scaleFont = useMemo(() => {
    const values = chart.dataPoints.map((d) => d.value);
    const min = Math.min(...values, 0);
    const max = Math.max(...values, 1);
    // Guard the degenerate case where every word has the same frequency.
    const span = max - min || 1;
    return (value: number) =>
      minFontSize + ((value - min) / span) * (maxFontSize - minFontSize);
  }, [chart.dataPoints, minFontSize, maxFontSize]);

  useEffect(() => {
    if (!width || chart.dataPoints.length === 0) {
      setPlaced([]);
      return;
    }

    let cancelled = false;

    const layout = cloud<PlacedWord>()
      .size([width, HEIGHT])
      .words(
        chart.dataPoints.map((d) => ({
          ...d,
          x: 0,
          y: 0,
          rotate: 0,
          size: scaleFont(d.value),
        })),
      )
      .padding(2)
      .font("system-ui, -apple-system, sans-serif")
      .fontSize((d) => d.size)
      .rotate((_, i) =>
        rotationAngles.length
          ? rotationAngles[i % rotationAngles.length]
          : 0,
      )
      // Deterministic placement: the default is Math.random, which reshuffles
      // the cloud on every re-render.
      .random(() => 0.5)
      .on("end", (words) => {
        if (!cancelled) setPlaced(words as PlacedWord[]);
      });

    layout.start();
    return () => {
      cancelled = true;
      layout.stop();
    };
  }, [chart.dataPoints, width, rotationAngles, scaleFont]);

  return (
    <div
      ref={containerRef}
      className="w-full flex items-center justify-center"
      style={{ height: HEIGHT }}
    >
      {placed.length > 0 && (
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label={chart.config.description || chart.config.title}
        >
          {/* d3-cloud positions words around an origin at the centre. */}
          <g transform={`translate(${width / 2}, ${HEIGHT / 2})`}>
            {placed.map((word, index) => (
              <text
                key={`${word.text}-${index}`}
                textAnchor="middle"
                transform={`translate(${word.x}, ${word.y}) rotate(${word.rotate})`}
                style={{
                  fontSize: word.size,
                  fontFamily: "system-ui, -apple-system, sans-serif",
                  fill: PALETTE[index % PALETTE.length],
                  cursor: "default",
                }}
              >
                <title>
                  {`${word.fullText}\nFrequency: ${word.value}\nPapers: ${word.totalPapers}`}
                </title>
                {word.text}
              </text>
            ))}
          </g>
        </svg>
      )}
    </div>
  );
}
