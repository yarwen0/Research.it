"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

export default function EditorByIdPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  useEffect(() => {
    router.replace(`/editor?id=${id}`);
  }, [id, router]);

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="text-center">
        <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        <p className="mt-4 text-gray-600">Loading review...</p>
      </div>
    </div>
  );
}
