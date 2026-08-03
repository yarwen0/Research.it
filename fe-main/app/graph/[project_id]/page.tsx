import { fetchGraph } from '@/lib/api';

import GraphClient from './_components/graph-client';

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

export default async function GraphPage({
    params,
}: {
    // Next 15 onwards resolves route params asynchronously.
    params: Promise<{ project_id: string }>;
}) {
    const { project_id } = await params;

    try {
        const graphData = await fetchGraph(project_id);
        return (
            <GraphClient
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
