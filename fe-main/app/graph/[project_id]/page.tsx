import dynamic from 'next/dynamic';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

// Dynamically import the graph renderer with no SSR
const RefGraphRenderer = dynamic(
    () => import('./_components/ref-graph-renderer'),
    { ssr: false }
);

export default async function GraphPage({ params }: { params: { project_id: string } }) {
    const project_id = params.project_id;

    const response = await fetch(`${API_BASE_URL}/api/graph/${project_id}/`, {
        cache: 'no-store',
    });

    if (!response.ok) {
        return (
            <div className="flex min-h-screen items-center justify-center p-8">
                <div className="text-center">
                    <h1 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                        Graph not found
                    </h1>
                    <p className="text-gray-600 dark:text-gray-400">
                        Could not load the citation graph for project {project_id}.
                    </p>
                </div>
            </div>
        );
    }

    const jsonData = await response.json();

    return <RefGraphRenderer data={jsonData} />;
}
