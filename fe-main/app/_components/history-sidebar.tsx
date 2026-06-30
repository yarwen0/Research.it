"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { History, Trash2, Clock, ChevronRight } from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  getStoredResponses,
  deleteResponse,
  clearAllResponses,
  formatTimestamp,
  formatDuration,
  type ResearchResponse,
} from "@/lib/response-store";
import { cn } from "@/lib/utils";

interface HistorySidebarProps {
  onSelectResponse: (response: ResearchResponse) => void;
  currentResponseId?: string;
  enableNavigation?: boolean; // Optional prop to enable/disable navigation
}

export function HistorySidebar({
  onSelectResponse,
  currentResponseId,
  enableNavigation = false,
}: HistorySidebarProps) {
  const [responses, setResponses] = useState<ResearchResponse[]>([]);
  const router = useRouter();

  useEffect(() => {
    loadResponses();
    
    // Set up a listener for storage changes
    const handleStorageChange = () => {
      loadResponses();
    };
    
    window.addEventListener('storage', handleStorageChange);
    // Also check periodically in case changes happen in the same tab
    const interval = setInterval(loadResponses, 1000);
    
    return () => {
      window.removeEventListener('storage', handleStorageChange);
      clearInterval(interval);
    };
  }, []);

  const loadResponses = () => {
    const stored = getStoredResponses();
    setResponses(stored);
  };

  const handleDelete = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    deleteResponse(id);
    loadResponses();
  };

  const handleClearAll = () => {
    if (confirm("Are you sure you want to delete all research history?")) {
      clearAllResponses();
      setResponses([]);
    }
  };

  const handleResponseClick = (response: ResearchResponse) => {
    if (enableNavigation) {
      router.push(`/r/${response.id}`);
    } else {
      onSelectResponse(response);
    }
  };

  const speedBadgeColor = {
    fast: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
    medium: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
    slow: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  };

  return (
    <Sidebar>
      <SidebarHeader className="border-b border-gray-200 dark:border-gray-800 p-4 bg-white dark:bg-gray-950">
        <div className="flex items-center gap-2 text-gray-900 dark:text-white">
          <History className="h-5 w-5" />
          <h2 className="text-lg font-semibold">Research History</h2>
        </div>
      </SidebarHeader>
      
      <SidebarContent className="bg-white dark:bg-gray-950">
        <SidebarGroup>
          <SidebarGroupLabel className="text-gray-700 dark:text-gray-300">Recent Searches</SidebarGroupLabel>
          <SidebarGroupContent>
            {responses.length === 0 ? (
              <div className="flex flex-col items-center justify-center text-center py-12 px-4">
                <History className="h-12 w-12 text-gray-400 dark:text-gray-600 mb-4" />
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  No research history yet
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-500 mt-2">
                  Your completed research will appear here
                </p>
              </div>
            ) : (
              <SidebarMenu>
                {responses.map((response) => (
                  <SidebarMenuItem key={response.id}>
                    <SidebarMenuButton
                      onClick={() => handleResponseClick(response)}
                      isActive={currentResponseId === response.id}
                      className="h-auto py-3 flex-col items-start group"
                    >
                      <div className="w-full">
                        <div className="flex items-start justify-between gap-2 mb-2">
                          <span className="text-sm font-medium line-clamp-2 flex-1 text-left">
                            {response.prompt}
                          </span>
                          <span
                            onClick={(e) => handleDelete(response.id, e)}
                            className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 inline-flex items-center justify-center cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 rounded-md"
                          >
                            <Trash2 className="h-3 w-3 text-destructive" />
                          </span>
                        </div>
                        
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <Clock className="h-3 w-3" />
                          <span>{formatTimestamp(response.timestamp)}</span>
                          {response.duration && (
                            <span className="text-gray-500 dark:text-gray-600">
                              · {formatDuration(response.duration)}
                            </span>
                          )}
                          <span
                            className={cn(
                              "px-2 py-0.5 rounded-full font-medium ml-auto",
                              speedBadgeColor[response.speedMode]
                            )}
                          >
                            {response.speedMode}
                          </span>
                        </div>
                        
                        {(response.papers || response.processed_papers) && (
                          <div className="mt-1 text-xs text-muted-foreground/70">
                            {response.total_papers || response.papers?.length || response.processed_papers?.length || 0} paper{((response.total_papers || response.papers?.length || response.processed_papers?.length || 0) !== 1) ? 's' : ''}
                          </div>
                        )}
                      </div>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            )}
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      
      {responses.length > 0 && (
        <SidebarFooter className="border-t border-gray-200 dark:border-gray-800 p-4 bg-white dark:bg-gray-950">
          <Button
            variant="destructive"
            size="sm"
            onClick={handleClearAll}
            className="w-full"
          >
            <Trash2 className="h-4 w-4 mr-2" />
            Clear All History
          </Button>
        </SidebarFooter>
      )}
    </Sidebar>
  );
}
