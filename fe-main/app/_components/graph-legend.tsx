"use client";

interface LegendItem {
  type: string;
  color: string;
  label: string;
}

const legendItems: LegendItem[] = [
  { type: "main", color: "#8b5cf6", label: "Research Topic" },
  { type: "paper", color: "#3b82f6", label: "Papers" },
  { type: "author", color: "#10b981", label: "Authors" },
  { type: "concept", color: "#f59e0b", label: "Concepts" },
  { type: "dataset", color: "#ef4444", label: "Datasets" },
  { type: "method", color: "#06b6d4", label: "Methods" },
  { type: "related", color: "#ec4899", label: "Related Work" },
];

export default function GraphLegend() {
  return (
    <div className="bg-card rounded-lg border border-border shadow-sm p-4">
      <h3 className="text-sm font-semibold text-foreground mb-3">Legend</h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {legendItems.map((item) => (
          <div key={item.type} className="flex items-center gap-2">
            <div
              className="w-4 h-4 rounded-full border-2 shadow-sm"
              style={{ 
                backgroundColor: item.color,
                borderColor: 'hsl(var(--border))'
              }}
            />
            <span className="text-xs text-muted-foreground">{item.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
