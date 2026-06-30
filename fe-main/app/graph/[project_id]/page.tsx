import dynamic from 'next/dynamic';

// Dynamically import the graph renderer with no SSR
const RefGraphRenderer = dynamic(
    () => import('./_components/ref-graph-renderer'),
    { ssr: false }
);

export default async function submitResearch(q: { params: { project_id: string } }) {
    const project_id = q.params.project_id;

    // Call backend API to get the graph data (disable Next.js caching)
    console.log("getting data ")
    const data = await fetch(`http://localhost:8000/api/graph/${project_id}`, {
        cache: 'no-store',  // Disable caching
    });
    const jsonData = await data.json();
    console.log("got data")

    return <RefGraphRenderer data={jsonData} />;
}