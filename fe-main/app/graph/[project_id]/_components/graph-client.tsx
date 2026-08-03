"use client";

import dynamic from "next/dynamic";

import type { GraphResponse } from "@/lib/api";

/**
 * Client boundary for the graph renderer.
 *
 * The renderer builds a Sigma/Graphology scene against `window`, so it cannot
 * be server-rendered. Next 16 rejects `ssr: false` inside a Server Component,
 * so the dynamic import has to live behind a "use client" boundary rather than
 * in the page itself.
 */
const RefGraphRenderer = dynamic(() => import("./ref-graph-renderer"), {
  ssr: false,
  loading: () => (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-gray-600 dark:text-gray-400">Loading citation graph…</p>
    </div>
  ),
});

export default function GraphClient({ data }: { data: GraphResponse }) {
  return <RefGraphRenderer data={data} />;
}
