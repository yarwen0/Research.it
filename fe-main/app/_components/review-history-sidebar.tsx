"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  FileText,
  Clock,
  CheckCircle,
  AlertCircle,
  Loader2,
  Trash2,
  Download,
  FileEdit,
  BarChart3,
} from "lucide-react";
import { useReviewStore, ReviewData } from "@/lib/review-store";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
} from "@/components/ui/sidebar";

interface ReviewHistorySidebarProps {
  currentReviewId: string | null;
  onSelectReview: (reviewId: string) => void;
}

export default function ReviewHistorySidebar({
  currentReviewId,
  onSelectReview,
}: ReviewHistorySidebarProps) {
  const reviewStore = useReviewStore();
  const router = useRouter();
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const allReviews = reviewStore.getAllReviews();
  const statistics = reviewStore.getStatistics();

  const formatDate = (timestamp: number) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const days = Math.floor(hours / 24);

    if (hours < 1) return "Just now";
    if (hours < 24) return `${hours}h ago`;
    if (days < 7) return `${days}d ago`;
    return date.toLocaleDateString();
  };

  const getStatusIcon = (status: ReviewData["status"]) => {
    switch (status) {
      case "completed":
        return <CheckCircle className="w-4 h-4 text-green-600" />;
      case "generating":
        return <Loader2 className="w-4 h-4 text-blue-600 animate-spin" />;
      case "error":
        return <AlertCircle className="w-4 h-4 text-red-600" />;
    }
  };

  const getStatusColor = (status: ReviewData["status"]) => {
    switch (status) {
      case "completed":
        return "bg-green-50 border-green-200 hover:bg-green-100";
      case "generating":
        return "bg-blue-50 border-blue-200 hover:bg-blue-100";
      case "error":
        return "bg-red-50 border-red-200 hover:bg-red-100";
    }
  };

  const handleDelete = (reviewId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (deleteConfirm === reviewId) {
      reviewStore.deleteReview(reviewId);
      setDeleteConfirm(null);
      if (currentReviewId === reviewId) {
        router.push("/editor");
      }
    } else {
      setDeleteConfirm(reviewId);
      setTimeout(() => setDeleteConfirm(null), 3000);
    }
  };

  const handleExport = (review: ReviewData, e: React.MouseEvent) => {
    e.stopPropagation();
    const blob = new Blob([review.latexContent], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `review-${review.paperTitle?.replace(/\s+/g, "-") || review.id}.tex`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Sidebar>
      <SidebarHeader className="p-4 border-b border-gray-200 bg-white dark:bg-gray-950">
        <div className="flex items-center gap-2 text-gray-900 dark:text-white">
          <FileEdit className="w-5 h-5" />
          <h2 className="font-semibold text-lg">Review History</h2>
        </div>
      </SidebarHeader>

      <SidebarContent className="bg-white dark:bg-gray-950">
        <SidebarGroup>
          <SidebarGroupLabel className="text-gray-700 dark:text-gray-300">Recent Reviews</SidebarGroupLabel>
          <SidebarGroupContent>
            {allReviews.length === 0 ? (
              <div className="flex flex-col items-center justify-center text-center py-12 px-4">
                <FileText className="h-12 w-12 text-gray-400 dark:text-gray-600 mb-4" />
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  No reviews yet
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-500 mt-2">
                  Start a new review to see it here
                </p>
              </div>
            ) : (
              <div className="p-3 space-y-2">
                {allReviews.map((review) => (
                    <motion.div
                      key={review.id}
                      initial={{ opacity: 0, y: -10 }}
                      animate={{ opacity: 1, y: 0 }}
                      className={`relative border rounded-lg p-3 cursor-pointer transition-all ${
                        currentReviewId === review.id
                          ? "ring-2 ring-blue-500 shadow-md"
                          : getStatusColor(review.status)
                      }`}
                      onClick={() => {
                        onSelectReview(review.id);
                      }}
                    >
                      {/* Status Badge */}
                      <div className="absolute top-2 right-2">
                        {getStatusIcon(review.status)}
                      </div>

                      {/* Paper Title */}
                      <h3 className="font-medium text-sm mb-1 pr-6 line-clamp-2">
                        {review.paperTitle || `Review #${review.paperIndex}`}
                      </h3>

                      {/* Metadata */}
                      <div className="space-y-1 text-xs text-gray-600 mb-2">
                        <div className="flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          <span>{formatDate(review.createdAt)}</span>
                        </div>
                        {review.statistics && (
                          <div className="flex items-center gap-1">
                            <BarChart3 className="w-3 h-3" />
                            <span>
                              {review.statistics.processed_papers} papers,{" "}
                              {review.statistics.relevant_chunks} chunks
                            </span>
                          </div>
                        )}
                      </div>

                      {/* Error Message */}
                      {review.status === "error" && review.error && (
                        <div className="text-xs text-red-600 mb-2 p-2 bg-red-50 rounded">
                          {review.error}
                        </div>
                      )}

                      {/* Actions */}
                      <div className="flex items-center gap-1 pt-2 border-t border-gray-200">
                        {review.status === "completed" && (
                          <button
                            onClick={(e) => handleExport(review, e)}
                            className="flex items-center gap-1 px-2 py-1 text-xs bg-blue-100 hover:bg-blue-200 text-blue-700 rounded transition-colors"
                          >
                            <Download className="w-3 h-3" />
                            Export
                          </button>
                        )}
                        <button
                          onClick={(e) => handleDelete(review.id, e)}
                          className={`flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors ml-auto ${
                            deleteConfirm === review.id
                              ? "bg-red-600 text-white"
                              : "bg-gray-100 hover:bg-red-100 text-gray-700 hover:text-red-700"
                          }`}
                        >
                          <Trash2 className="w-3 h-3" />
                          {deleteConfirm === review.id ? "Confirm?" : "Delete"}
                        </button>
                      </div>
                    </motion.div>
                  ))}
              </div>
            )}
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="p-3 border-t border-gray-200 bg-gray-50">
            <button
              onClick={() => {
                if (confirm("Are you sure you want to clear all reviews?")) {
                  reviewStore.clearAllReviews();
                  router.push("/editor");
                }
              }}
              className="w-full px-3 py-2 text-xs bg-gray-200 hover:bg-gray-300 text-gray-700 rounded transition-colors"
            >
              Clear All History
            </button>
          </SidebarFooter>
        </Sidebar>
  );
}
