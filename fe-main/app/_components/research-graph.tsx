"use client";
import { useEffect, useRef, useState } from "react";
import cytoscape from "cytoscape";
import { ZoomIn, ZoomOut, Maximize2, RefreshCw } from "lucide-react";
// @ts-ignore - no types available for cytoscape-fcose
import fcose from "cytoscape-fcose";

// Register the fcose layout
if (typeof cytoscape !== 'undefined') {
  cytoscape.use(fcose);
}

interface GraphNode {
  id: string;
  label: string;
  type?: string;
}

interface GraphEdge {
  source: string;
  target: string;
  label?: string;
}

interface ResearchGraphProps {
  nodes?: GraphNode[];
  edges?: GraphEdge[];
}

// Hook to detect dark mode
function useDarkMode() {
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    const checkDarkMode = () => {
      setIsDark(document.documentElement.classList.contains('dark'));
    };

    checkDarkMode();

    const observer = new MutationObserver(checkDarkMode);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    });

    return () => observer.disconnect();
  }, []);

  return isDark;
}

interface ResearchGraphProps {
  nodes?: GraphNode[];
  edges?: GraphEdge[];
}

// Mock data for demonstration
const mockNodes: GraphNode[] = [
  { id: "1", label: "Research Topic", type: "main" },
  { id: "2", label: "Paper A", type: "paper" },
  { id: "3", label: "Paper B", type: "paper" },
  { id: "4", label: "Paper C", type: "paper" },
  { id: "5", label: "Author 1", type: "author" },
  { id: "6", label: "Author 2", type: "author" },
  { id: "7", label: "Concept X", type: "concept" },
  { id: "8", label: "Concept Y", type: "concept" },
  { id: "9", label: "Dataset A", type: "dataset" },
  { id: "10", label: "Method 1", type: "method" },
  { id: "11", label: "Method 2", type: "method" },
  { id: "12", label: "Related Work", type: "related" },
];

const mockEdges: GraphEdge[] = [
  { source: "1", target: "2", label: "cites" },
  { source: "1", target: "3", label: "cites" },
  { source: "1", target: "4", label: "cites" },
  { source: "2", target: "5", label: "authored_by" },
  { source: "3", target: "5", label: "authored_by" },
  { source: "3", target: "6", label: "authored_by" },
  { source: "4", target: "6", label: "authored_by" },
  { source: "2", target: "7", label: "discusses" },
  { source: "3", target: "7", label: "discusses" },
  { source: "3", target: "8", label: "discusses" },
  { source: "4", target: "8", label: "discusses" },
  { source: "2", target: "9", label: "uses" },
  { source: "4", target: "9", label: "uses" },
  { source: "2", target: "10", label: "implements" },
  { source: "3", target: "11", label: "implements" },
  { source: "4", target: "12", label: "references" },
  { source: "7", target: "8", label: "relates_to" },
];

const getNodeColor = (type?: string) => {
  switch (type) {
    case "main":
      return "#8b5cf6"; // purple
    case "paper":
      return "#3b82f6"; // blue
    case "author":
      return "#10b981"; // green
    case "concept":
      return "#f59e0b"; // amber
    case "dataset":
      return "#ef4444"; // red
    case "method":
      return "#06b6d4"; // cyan
    case "related":
      return "#ec4899"; // pink
    default:
      return "#6b7280"; // gray
  }
};

const getNodeSize = (label: string, type?: string) => {
  // Calculate size based on label length
  const baseSize = type === "main" ? 80 : 50;
  const labelLength = label.length;
  
  // Scale up based on text length, with a minimum and maximum
  const scaledSize = Math.max(baseSize, Math.min(labelLength * 8, 150));
  
  return scaledSize;
};

export default function ResearchGraph({ nodes, edges }: ResearchGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphContainerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const isDark = useDarkMode();
  const [isFullscreen, setIsFullscreen] = useState(false);

  const handleZoomIn = () => {
    if (cyRef.current) {
      cyRef.current.zoom(cyRef.current.zoom() * 1.2);
      cyRef.current.center();
    }
  };

  const handleZoomOut = () => {
    if (cyRef.current) {
      cyRef.current.zoom(cyRef.current.zoom() * 0.8);
      cyRef.current.center();
    }
  };

  const handleFit = () => {
    if (cyRef.current) {
      cyRef.current.fit(undefined, 50);
    }
  };

  const handleFullscreen = async () => {
    if (!graphContainerRef.current) return;

    try {
      if (!document.fullscreenElement) {
        await graphContainerRef.current.requestFullscreen();
        setIsFullscreen(true);
      } else {
        await document.exitFullscreen();
        setIsFullscreen(false);
      }
    } catch (error) {
      console.error("Fullscreen error:", error);
    }
  };

  const handleReset = () => {
    if (cyRef.current) {
      cyRef.current.layout({ name: "fcose", ...layoutOptions } as any).run();
    }
  };

  // Listen for fullscreen changes
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
      // Resize cytoscape when entering/exiting fullscreen
      if (cyRef.current) {
        setTimeout(() => {
          cyRef.current?.resize();
          cyRef.current?.fit(undefined, 50);
        }, 100);
      }
    };

    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
    };
  }, []);

  const layoutOptions = {
    randomize: true,
    animate: true,
    animationDuration: 1000,
    fit: true,
    padding: 80,
    nodeSeparation: 200,
    nodeRepulsion: 15000,
    idealEdgeLength: 200,
    edgeElasticity: 0.3,
    nestingFactor: 0.1,
    gravity: 0.2,
    numIter: 3000,
    tile: true,
    tilingPaddingVertical: 20,
    tilingPaddingHorizontal: 20,
    gravityRangeCompound: 1.5,
    gravityCompound: 1.0,
    gravityRange: 3.8,
  };

  useEffect(() => {
    if (!containerRef.current) return;

    // Use provided data or fall back to mock data
    const displayNodes = nodes || mockNodes;
    const displayEdges = edges || mockEdges;

    // Theme-aware colors
    const bgColor = isDark ? '#1e293b' : '#ffffff';
    const textColor = isDark ? '#f1f5f9' : '#1e293b';
    const borderColor = isDark ? '#334155' : '#e2e8f0';
    const edgeColor = isDark ? '#64748b' : '#94a3b8';
    const edgeLabelBg = isDark ? '#1e293b' : '#ffffff';
    const selectedEdgeColor = isDark ? '#60a5fa' : '#3b82f6';

    // Initialize Cytoscape
    const cy = cytoscape({
      container: containerRef.current,
      elements: [
        ...displayNodes.map((node) => ({
          data: { 
            id: node.id, 
            label: node.label,
            type: node.type 
          },
        })),
        ...displayEdges.map((edge) => ({
          data: {
            source: edge.source,
            target: edge.target,
            label: edge.label,
          },
        })),
      ],
      style: [
        {
          selector: "node",
          style: {
            "background-color": (ele: any) => getNodeColor(ele.data("type")),
            label: "data(label)",
            color: textColor,
            "text-valign": "center",
            "text-halign": "center",
            "font-size": "13px",
            "font-weight": 600 as any,
            width: (ele: any) => getNodeSize(ele.data("label"), ele.data("type")),
            height: (ele: any) => getNodeSize(ele.data("label"), ele.data("type")),
            "text-wrap": "wrap",
            "text-max-width": (ele: any) => `${getNodeSize(ele.data("label"), ele.data("type")) * 0.8}px`,
            "overlay-padding": "8px",
            "z-index": 10 as any,
            "border-width": "0px",
            shape: "ellipse",
          },
        },
        {
          selector: "node:selected",
          style: {
            "border-width": "3px",
            "border-color": selectedEdgeColor,
            "border-opacity": 1 as any,
          },
        },
        {
          selector: "edge",
          style: {
            width: 2,
            "line-color": edgeColor,
            "target-arrow-color": edgeColor,
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            "arrow-scale": 1.5,
            label: "data(label)",
            "font-size": "10px",
            color: isDark ? "#94a3b8" : "#64748b",
            "text-background-color": edgeLabelBg,
            "text-background-opacity": 0.9,
            "text-background-padding": "3px",
            "text-rotation": "autorotate",
          },
        },
        {
          selector: "edge:selected",
          style: {
            width: 3,
            "line-color": selectedEdgeColor,
            "target-arrow-color": selectedEdgeColor,
          },
        },
      ],
      layout: {
        name: "fcose",
        ...layoutOptions,
      } as any,
    });

    cyRef.current = cy;

    // Add zoom controls with mouse wheel
    cy.on("wheel", (e) => {
      e.preventDefault();
    });

    // Cleanup
    return () => {
      if (cyRef.current) {
        cyRef.current.destroy();
        cyRef.current = null;
      }
    };
  }, [nodes, edges, isDark]);

  return (
    <div 
      ref={graphContainerRef}
      className={`w-full rounded-lg border border-border bg-card shadow-lg overflow-hidden relative ${
        isFullscreen ? 'h-screen' : 'h-[600px]'
      }`}
    >
      {/* Graph Controls */}
      <div className="absolute top-4 right-4 z-10 flex flex-col gap-2">
        <button
          onClick={handleZoomIn}
          className="p-2 bg-card rounded-lg border border-border shadow-sm hover:bg-accent transition-colors"
          title="Zoom In"
        >
          <ZoomIn className="w-4 h-4 text-foreground" />
        </button>
        <button
          onClick={handleZoomOut}
          className="p-2 bg-card rounded-lg border border-border shadow-sm hover:bg-accent transition-colors"
          title="Zoom Out"
        >
          <ZoomOut className="w-4 h-4 text-foreground" />
        </button>
        <button
          onClick={handleFullscreen}
          className="p-2 bg-card rounded-lg border border-border shadow-sm hover:bg-accent transition-colors"
          title={isFullscreen ? "Exit Fullscreen" : "Fullscreen"}
        >
          <Maximize2 className="w-4 h-4 text-foreground" />
        </button>
        <button
          onClick={handleReset}
          className="p-2 bg-card rounded-lg border border-border shadow-sm hover:bg-accent transition-colors"
          title="Reset Layout"
        >
          <RefreshCw className="w-4 h-4 text-foreground" />
        </button>
      </div>
      
      <div ref={containerRef} className="w-full h-full" />
    </div>
  );
}
