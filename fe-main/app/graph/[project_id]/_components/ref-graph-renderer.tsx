"use client";

import { useEffect, useRef, useState } from 'react';
import Graph from 'graphology';
import Sigma from 'sigma';
import forceAtlas2 from 'graphology-layout-forceatlas2';
import { ZoomIn, ZoomOut, Maximize2, RefreshCw } from 'lucide-react';

export default function RefGraphRenderer({
    data,
}: {
    data: any
}) {
    const rawNodes: any[] = data.graph_data["nodes"] || [];
    const rawEdges: any[] = data.graph_data["edges"] || [];
    
    const containerRef = useRef<HTMLDivElement>(null);
    const sigmaRef = useRef<Sigma | null>(null);
    const graphRef = useRef<Graph | null>(null);
    const hoveredNodeRef = useRef<string | null>(null);
    const selectedNodeRef = useRef<string | null>(null);
    const [selectedNode, setSelectedNode] = useState<string | null>(null);
    const [hoveredNode, setHoveredNode] = useState<string | null>(null);
    const [hoveredNodeData, setHoveredNodeData] = useState<any>(null);

    useEffect(() => {
        if (!containerRef.current || rawNodes.length === 0) return;

        // Create a new graph
        const graph = new Graph();
        graphRef.current = graph;

        // Add nodes
        rawNodes.forEach((node) => {
            const nodeData = node.data;
            const isProcessed = nodeData.is_processed;
            const nodeType = nodeData.node_type || 'paper';
            
            // Different styling for authors vs papers
            let nodeColor = '#5db899ff'; // default gray (unprocessed papers)
            let nodeSize = 7; // unprocessed paper size
            
            if (nodeType === 'author') {
                nodeColor = '#afa09cff'; // green for authors
                nodeSize = 4; // smaller than unprocessed papers
            } else if (isProcessed) {
                nodeColor = '#3b82f6'; // blue for processed papers
                nodeSize = 15; // large
            }
            
            graph.addNode(nodeData.id, {
                x: Math.random() * 100,
                y: Math.random() * 100,
                size: nodeSize,
                label: nodeData.title || nodeData.label || nodeData.id,
                color: nodeColor,
                isProcessed: isProcessed,
                nodeType: nodeType,
                ...nodeData,
            });
        });

        // Add edges
        rawEdges.forEach((edge) => {
            const edgeData = edge.data;
            const edgeType = edgeData.edge_type || 'citation';
            
            try {
                if (graph.hasNode(edgeData.source) && graph.hasNode(edgeData.target)) {
                    // Different styling for authorship vs citation edges
                    const edgeColor = edgeType === 'authorship' ? '#64748ba8' : '#44967aff';
                    const edgeSize = edgeType === 'authorship' ? 1 : 2;
                    
                    graph.addEdge(edgeData.source, edgeData.target, {
                        size: edgeSize,
                        color: edgeColor,
                        type: 'arrow',
                        edgeType: edgeType,
                    });
                }
            } catch (e) {
                // Edge might already exist
                console.warn('Failed to add edge:', e);
            }
        });

        // Apply ForceAtlas2 layout
        const settings = forceAtlas2.assign(graph, {
            iterations: 50,
            settings: {
                gravity: .2,
                scalingRatio: 10,
                strongGravityMode: true,
                barnesHutOptimize: true,
                slowDown: 10,
            }
        });

        // Store camera ratio for access in reducers
        let cameraRatio = 1;

        // Create Sigma instance with custom reducers for hover highlighting
        const sigma = new Sigma(graph, containerRef.current, {
            renderEdgeLabels: false,
            defaultNodeType: 'circle',
            defaultEdgeType: 'arrow',
            labelRenderedSizeThreshold: -1, // Disable default label rendering
            // Node reducer - only show labels on hover or when selected
            nodeReducer: (node, data) => {
                const res = { ...data };
                
                // Hide all labels by default
                res.label = '';
                
                if (data.dimmed) {
                    res.color = '#e5e7eb'; // Very light gray for dimmed nodes
                } else if (data.highlighted || data.selected) {
                    // Slightly enlarge and brighten highlighted/selected nodes
                    res.size = data.size * 1.3;
                    res.zIndex = 1;
                    
                    // Calculate actual rendered pixel size using camera ratio
                    const actualRenderedSize = (data.size || 1) * cameraRatio;
                    
                    // Show label for hovered/selected node always
                    if (node === hoveredNodeRef.current || node === selectedNodeRef.current) {
                        res.label = data.label;
                        if (data.nodeType === 'author') {
                            res.labelSize = 10;
                        } else if (!data.isProcessed) {
                            res.labelSize = 12;
                        } else {
                            res.labelSize = 14;
                        }
                    } else {
                        // Show labels for connected nodes based on zoom level
                        // Different thresholds for different node types
                        let showLabel = false;
                        
                        if (data.nodeType === 'author') {
                            // Authors: need to be zoomed in (small actualRenderedSize)
                            showLabel = actualRenderedSize < 8;
                            res.labelSize = 8;
                        } else if (!data.isProcessed) {
                            // Unprocessed papers: medium zoom
                            showLabel = actualRenderedSize < 12;
                            res.labelSize = 10;
                        } else {
                            // Processed papers: visible at lower zoom
                            showLabel = actualRenderedSize < 20;
                            res.labelSize = 12;
                        }
                        
                        if (showLabel) {
                            res.label = data.label;
                        }
                    }
                }
                
                return res;
            },
            // Edge reducer to handle hover highlighting and selection
            edgeReducer: (edge, data) => {
                const res = { ...data };
                
                if (data.hidden) {
                    // Hidden edges should be almost invisible
                    res.color = '#f3f4f6'; // Very light gray for hidden edges
                    res.size = 0.5; // Make hidden edges very thin
                    res.alpha = 0.05; // Almost transparent
                } else if (data.highlighted || data.selected) {
                    // Make highlighted/selected edges more prominent
                    res.size = data.size * 1.5;
                    res.zIndex = 1;
                    // Increase opacity when highlighted/selected
                    if (data.edgeType === 'authorship') {
                        res.alpha = 0.6;
                    }
                } else {
                    // Default state - set opacity for authorship edges
                    if (data.edgeType === 'authorship') {
                        res.forceLabel = true;
                        res.alpha = 0.2; // Low opacity for author connections
                    }
                }
                
                return res;
            },
        });
        sigmaRef.current = sigma;

        // Update camera ratio on camera updates (zoom/pan) and refresh to recompute labels
        const camera = sigma.getCamera();
        camera.on('updated', () => {
            cameraRatio = camera.ratio;
            sigma.refresh(); // Trigger reducer recomputation
        });

        // Initialize camera ratio
        cameraRatio = camera.ratio;

        // Add click handler for nodes
        sigma.on('clickNode', ({ node }) => {
            // Clear all previous highlighting attributes
            graph.forEachNode((n) => {
                graph.removeNodeAttribute(n, 'selected');
                graph.removeNodeAttribute(n, 'dimmed');
                graph.removeNodeAttribute(n, 'highlighted');
            });
            graph.forEachEdge((edge) => {
                graph.removeEdgeAttribute(edge, 'selected');
                graph.removeEdgeAttribute(edge, 'highlighted');
                graph.removeEdgeAttribute(edge, 'hidden');
            });
            
            selectedNodeRef.current = node;
            setSelectedNode(node);
            const nodeData = graph.getNodeAttributes(node);

            // Set selected state for clicked node and its neighbors
            const neighbors = new Set<string>();
            neighbors.add(node);
            
            graph.forEachEdge(node, (edge, attributes, source, target) => {
                neighbors.add(source);
                neighbors.add(target);
                graph.setEdgeAttribute(edge, 'selected', true);
            });
            
            // Update node styles
            graph.forEachNode((n) => {
                if (neighbors.has(n)) {
                    graph.setNodeAttribute(n, 'selected', true);
                } else {
                    graph.setNodeAttribute(n, 'dimmed', true);
                }
            });
            
            // Update edge styles - hide edges not connected to selected node
            graph.forEachEdge((edge, attributes, source, target) => {
                if (!neighbors.has(source) || !neighbors.has(target)) {
                    graph.setEdgeAttribute(edge, 'hidden', true);
                }
            });
            
            sigma.refresh();
        });

        // Add click handler for stage (background)
        sigma.on('clickStage', () => {
            // Clear selection
            if (selectedNodeRef.current) {
                selectedNodeRef.current = null;
                setSelectedNode(null);
                
                // Clear all highlighting attributes
                graph.forEachNode((n) => {
                    graph.removeNodeAttribute(n, 'selected');
                    graph.removeNodeAttribute(n, 'dimmed');
                    graph.removeNodeAttribute(n, 'highlighted');
                });
                graph.forEachEdge((edge) => {
                    graph.removeEdgeAttribute(edge, 'selected');
                    graph.removeEdgeAttribute(edge, 'highlighted');
                    graph.removeEdgeAttribute(edge, 'hidden');
                });
                
                sigma.refresh();
            }
        });

        // Add hover highlighting (only if no node is selected)
        sigma.on('enterNode', ({ node }) => {
            hoveredNodeRef.current = node;
            setHoveredNode(node);
            const nodeData = graph.getNodeAttributes(node);
            setHoveredNodeData(nodeData);
            
            // Don't override selection highlighting
            if (selectedNodeRef.current) {
                sigma.refresh();
                return;
            }
            
            // Get neighbors (connected nodes)
            const neighbors = new Set<string>();
            neighbors.add(node);
            
            graph.forEachEdge(node, (edge, attributes, source, target) => {
                neighbors.add(source);
                neighbors.add(target);
            });
            
            // Update node styles - highlight connected, dim others
            graph.forEachNode((n, attributes) => {
                if (neighbors.has(n)) {
                    // Highlight connected nodes
                    graph.setNodeAttribute(n, 'highlighted', true);
                } else {
                    // Dim unconnected nodes (unless selected)
                    if (!graph.getNodeAttribute(n, 'selected')) {
                        graph.setNodeAttribute(n, 'dimmed', true);
                    }
                }
            });
            
            // Update edge styles - highlight connected, dim others
            graph.forEachEdge((edge, attributes, source, target) => {
                if (neighbors.has(source) && neighbors.has(target)) {
                    graph.setEdgeAttribute(edge, 'highlighted', true);
                } else {
                    graph.setEdgeAttribute(edge, 'hidden', true);
                }
            });
            
            sigma.refresh();
        });
        
        sigma.on('leaveNode', () => {
            hoveredNodeRef.current = null;
            setHoveredNode(null);
            setHoveredNodeData(null);
            
            // Don't clear highlighting if a node is selected
            if (selectedNodeRef.current) {
                sigma.refresh();
                return;
            }
            
            // Reset all node and edge attributes
            graph.forEachNode((node) => {
                graph.removeNodeAttribute(node, 'highlighted');
                graph.removeNodeAttribute(node, 'dimmed');
            });
            
            graph.forEachEdge((edge) => {
                graph.removeEdgeAttribute(edge, 'highlighted');
                graph.removeEdgeAttribute(edge, 'hidden');
            });
            
            sigma.refresh();
        });

        // Cleanup
        return () => {
            sigma.kill();
            graph.clear();
        };
    }, [rawNodes, rawEdges]);

    const handleZoomIn = () => {
        if (sigmaRef.current) {
            const camera = sigmaRef.current.getCamera();
            camera.animatedZoom({ duration: 200 });
        }
    };

    const handleZoomOut = () => {
        if (sigmaRef.current) {
            const camera = sigmaRef.current.getCamera();
            camera.animatedUnzoom({ duration: 200 });
        }
    };

    const handleReset = () => {
        if (sigmaRef.current) {
            const camera = sigmaRef.current.getCamera();
            camera.animatedReset({ duration: 200 });
        }
    };

    const handleRelayout = () => {
        if (graphRef.current) {
            forceAtlas2.assign(graphRef.current, {
                iterations: 50,
                settings: {
                    gravity: 0,
                    scalingRatio: 100,
                    strongGravityMode: false,
                    barnesHutOptimize: true,
                    slowDown: 10,
                }
            });
            sigmaRef.current?.refresh();
        }
    };

    return (
        <div className="w-full h-screen rounded-lg border border-border bg-card shadow-lg overflow-hidden relative">
            {/* Graph Controls */}
            <div className="absolute top-4 right-4 z-10 flex flex-col gap-2">
                <button
                    type="button"
                    onClick={handleZoomIn}
                    className="p-2 bg-card rounded-lg border border-border shadow-sm hover:bg-accent transition-colors"
                    title="Zoom In"
                    aria-label="Zoom in"
                >
                    <ZoomIn className="w-4 h-4 text-foreground" />
                </button>
                <button
                    type="button"
                    onClick={handleZoomOut}
                    className="p-2 bg-card rounded-lg border border-border shadow-sm hover:bg-accent transition-colors"
                    title="Zoom Out"
                    aria-label="Zoom out"
                >
                    <ZoomOut className="w-4 h-4 text-foreground" />
                </button>
                <button
                    type="button"
                    onClick={handleReset}
                    className="p-2 bg-card rounded-lg border border-border shadow-sm hover:bg-accent transition-colors"
                    title="Reset View"
                    aria-label="Reset view"
                >
                    <Maximize2 className="w-4 h-4 text-foreground" />
                </button>
                <button
                    type="button"
                    onClick={handleRelayout}
                    className="p-2 bg-card rounded-lg border border-border shadow-sm hover:bg-accent transition-colors"
                    title="Relayout Graph"
                    aria-label="Relayout graph"
                >
                    <RefreshCw className="w-4 h-4 text-foreground" />
                </button>
            </div>

            {/* Hover Tooltip Panel */}
            {hoveredNodeData && (
                <div className="absolute top-4 left-4 z-10 bg-card/95 backdrop-blur-sm border border-border rounded-lg p-4 shadow-xl max-w-sm">
                    {hoveredNodeData.nodeType === 'author' ? (
                        <>
                            <div className="flex items-center gap-2 mb-2">
                                <div className="w-3 h-3 rounded-full bg-green-500"></div>
                                <h3 className="font-semibold text-sm text-green-600">Author</h3>
                            </div>
                            <p className="text-sm text-foreground font-medium">
                                {hoveredNodeData.label || hoveredNodeData.id}
                            </p>
                        </>
                    ) : (
                        <>
                            <div className="flex items-center gap-2 mb-2">
                                <div className={`w-3 h-3 rounded-full ${hoveredNodeData.isProcessed ? 'bg-blue-500' : 'bg-gray-400'}`}></div>
                                <h3 className="font-semibold text-sm">
                                    {hoveredNodeData.isProcessed ? 'Processed Paper' : 'Reference Paper'}
                                </h3>
                            </div>
                            <p className="text-sm text-foreground font-medium line-clamp-3 mb-2">
                                {hoveredNodeData.title || hoveredNodeData.label || hoveredNodeData.id}
                            </p>
                            {hoveredNodeData.authors && (
                                <p className="text-xs text-muted-foreground">
                                    Authors: {Array.isArray(hoveredNodeData.authors) 
                                        ? hoveredNodeData.authors.join(', ') 
                                        : hoveredNodeData.authors}
                                </p>
                            )}
                            {hoveredNodeData.year && (
                                <p className="text-xs text-muted-foreground mt-1">
                                    Year: {hoveredNodeData.year}
                                </p>
                            )}
                        </>
                    )}
                </div>
            )}

            {/* Selected Node Info */}
            {selectedNode && graphRef.current && (
                <div className="absolute bottom-4 left-4 z-10 bg-card border border-border rounded-lg p-4 shadow-lg max-w-md">
                    {graphRef.current.getNodeAttribute(selectedNode, 'nodeType') === 'author' ? (
                        <>
                            <h3 className="font-semibold text-sm mb-2 text-green-600">Author</h3>
                            <p className="text-xs text-muted-foreground truncate">
                                {graphRef.current.getNodeAttribute(selectedNode, 'label') || selectedNode}
                            </p>
                        </>
                    ) : (
                        <>
                            <h3 className="font-semibold text-sm mb-2">Paper</h3>
                            <p className="text-xs text-muted-foreground truncate">
                                {graphRef.current.getNodeAttribute(selectedNode, 'title') || selectedNode}
                            </p>
                            <p className="text-xs text-muted-foreground mt-1">
                                Status: {graphRef.current.getNodeAttribute(selectedNode, 'isProcessed') ? 'Processed' : 'Unprocessed'}
                            </p>
                        </>
                    )}
                </div>
            )}

            <div 
                ref={containerRef} 
                className="w-full h-full"
                style={{
                    backgroundImage: 'radial-gradient(circle, #dcdfe4ff 1px, transparent 1px)',
                    backgroundSize: '20px 20px',
                }}
            />
        </div>
    );
}