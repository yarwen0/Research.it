import dynamic from 'next/dynamic';
import { fetchGraph } from '@/lib/api';

// Dynamically import the graph renderer with no SSR
const RefGraphRenderer = dynamic(
    () => import('./_components/ref-graph-renderer'),
    { ssr: false }
);

function GraphNotFound({ projectId }: { projectId: string }) {
    return (
        <div className="flex min-h-screen items-center justify-center p-8">
            <div className="text-center">
                <h1 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                    Graph not found
                </h1>
                <p className="text-gray-600 dark:text-gray-400">
                    Could not load the citation graph for project {projectId}.
                </p>
            </div>
        </div>
    );
}

export default async function GraphPage({ params }: { params: { project_id: string } }) {
    const project_id = params.project_id;

    try {
        const graphData = await fetchGraph(project_id);
        return (
            <RefGraphRenderer
                data={{
                    status: 'success',
                    project_id,
                    graph_data: graphData,
                }}
            />
        );
    } catch {
        return <GraphNotFound projectId={project_id} />;
    }
}
