import { createServer } from "node:http";

// The graph route fetches on the Next server, beyond page.route's reach.
// This fixture complements the existing browser-level research-flow stub.
const graph = {
  status: "success", project_id: "a11yproject",
  graph_data: {
    nodes: [
      { data: { id: "paper1", title: "Accessible research interfaces", node_type: "paper", year: 2024, authors: ["Example Researcher"], is_processed: true } },
      { data: { id: "paper2", title: "Keyboard navigation in citation networks", node_type: "paper", year: 2023, authors: ["Sample Author"] } },
    ],
    edges: [{ data: { id: "edge1", source: "paper1", target: "paper2", edge_type: "cites" } }],
  },
};
createServer((req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Content-Type", "application/json");
  if (req.url?.startsWith("/api/graph/a11yproject")) res.end(JSON.stringify(graph));
  else if (req.url === "/health") res.end('{"status":"ok"}');
  else { res.statusCode = 404; res.end('{"detail":"Not found"}'); }
}).listen(8000, "127.0.0.1");
