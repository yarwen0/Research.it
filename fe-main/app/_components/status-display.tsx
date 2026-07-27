"use client";
import { SSEUpdate, StatusType } from "@/lib/stream_handler";
import {
  Loader2,
  CheckCircle2,
  XCircle,
  Sparkles,
  TrendingUp,
  Clock,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useState, useRef, useEffect } from "react";

interface StatusDisplayProps {
  updates: SSEUpdate[];
  isLoading: boolean;
}

const getStatusIcon = (status: StatusType, isLoading: boolean, isLastUpdate: boolean) => {
  // If not loading and not the last update, show check icon for completed items
  if (!isLoading && !isLastUpdate && status === StatusType.PROCESSING) {
    return <CheckCircle2 className="w-4 h-4 text-green-500" />;
  }
  
  switch (status) {
    case StatusType.PROCESSING:
      return <Loader2 className={`w-4 h-4 text-blue-500 ${isLoading && isLastUpdate ? 'animate-spin' : ''}`} />;
    case StatusType.PROGRESS:
      return <TrendingUp className="w-4 h-4 text-purple-500" />;
    case StatusType.SUCCESS:
      return <CheckCircle2 className="w-4 h-4 text-green-500" />;
    case StatusType.COMPLETED:
      return <CheckCircle2 className="w-4 h-4 text-emerald-500" />;
    case StatusType.ERROR:
      return <XCircle className="w-4 h-4 text-red-500" />;
    default:
      return <Clock className="w-4 h-4 text-gray-500" />;
  }
};

const getStatusColor = (status: StatusType) => {
  switch (status) {
    case StatusType.PROCESSING:
      return "border-blue-500/20 bg-blue-500/5";
    case StatusType.PROGRESS:
      return "border-purple-500/20 bg-purple-500/5";
    case StatusType.SUCCESS:
      return "border-green-500/20 bg-green-500/5";
    case StatusType.COMPLETED:
      return "border-emerald-500/20 bg-emerald-500/5";
    case StatusType.ERROR:
      return "border-red-500/20 bg-red-500/5";
    default:
      return "border-gray-500/20 bg-gray-500/5";
  }
};

export default function StatusDisplay({ updates, isLoading }: StatusDisplayProps) {
  const [showCompleted, setShowCompleted] = useState(false);
  const [startTime, setStartTime] = useState<number | null>(null);
  const [elapsedTime, setElapsedTime] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  // Set start time when first update arrives (use the timestamp from the first update if available)
  useEffect(() => {
    if (updates.length > 0 && !startTime) {
      const firstUpdateTime = (updates[0] as any).timestamp || Date.now();
      setStartTime(firstUpdateTime);
    }
  }, [updates.length, startTime]);

  // Update elapsed time every second (or calculate from last update when loading is complete)
  useEffect(() => {
    if (!startTime) return;

    const updateElapsed = () => {
      let endTime: number;
      
      if (isLoading) {
        // While loading, use current time
        endTime = Date.now();
      } else {
        // When complete, use the last update's timestamp
        const lastUpdate = updates[updates.length - 1];
        endTime = (lastUpdate as any)?.timestamp || Date.now();
      }
      
      const diff = Math.floor((endTime - startTime) / 1000);
      
      // Don't show time if 0 seconds
      if (diff === 0) {
        setElapsedTime("");
      } else if (diff < 60) {
        setElapsedTime(`${diff}s`);
      } else {
        const minutes = Math.floor(diff / 60);
        const seconds = diff % 60;
        setElapsedTime(`${minutes}m ${seconds}s`);
      }
    };

    updateElapsed();
    
    // Only update interval if still loading
    if (isLoading) {
      const interval = setInterval(updateElapsed, 1000);
      return () => clearInterval(interval);
    }
  }, [startTime, isLoading, updates]);

  // Auto-scroll to bottom when new updates arrive
  useEffect(() => {
    if (scrollRef.current && !showCompleted) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [updates, showCompleted]);

  if (!isLoading && updates.length === 0) {
    return null;
  }

  const lastUpdate = updates[updates.length - 1];
  
  // Separate updates by type
  const completedUpdates = updates.filter(
    (u) => u.status === StatusType.COMPLETED || u.status === StatusType.SUCCESS
  );
  const progressUpdates = updates.filter(
    (u) => u.status === StatusType.PROGRESS
  );
  const processingUpdates = updates.filter(
    (u) => u.status === StatusType.PROCESSING
  );
  
  // If loading is complete, only show progress and completed updates
  const activeUpdates = isLoading 
    ? [...processingUpdates, ...progressUpdates]
    : progressUpdates;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="w-full"
    >
      <div className="border border-gray-200 dark:border-gray-800 rounded-2xl bg-white/50 dark:bg-gray-900/50 backdrop-blur-sm shadow-lg overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-800 bg-gradient-to-r from-blue-50 to-purple-50 dark:from-blue-950/20 dark:to-purple-950/20">
          <div className="flex items-center gap-3">
            <motion.div
              animate={{
                rotate: isLoading ? 360 : 0,
                scale: isLoading ? [1, 1.2, 1] : 1,
              }}
              transition={{
                rotate: { 
                  duration: 2, 
                  repeat: isLoading ? Infinity : 0, 
                  ease: "linear" 
                },
                scale: { 
                  duration: 1, 
                  repeat: isLoading ? Infinity : 0, 
                  ease: "easeInOut" 
                },
              }}
            >
              {isLoading ? (
                <Sparkles className="w-5 h-5 text-purple-600 dark:text-purple-400" />
              ) : (
                <CheckCircle2 className="w-5 h-5 text-green-600 dark:text-green-400" />
              )}
            </motion.div>
            <div className="flex-1">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                  {isLoading ? "Research in Progress" : "Research Complete"}
                </h3>
                {elapsedTime && (
                  <span className="text-xs text-gray-500 dark:text-gray-400 font-medium">
                    {isLoading ? `Running: ${elapsedTime}` : `Completed in ${elapsedTime}`}
                  </span>
                )}
              </div>
              {lastUpdate && (
                <p className="text-xs text-gray-600 dark:text-gray-400 mt-0.5">
                  {lastUpdate.message}
                </p>
              )}
            </div>
            {isLoading && (
              <motion.div
                animate={{ scale: [1, 1.2, 1] }}
                transition={{ 
                  duration: 1.5, 
                  repeat: isLoading ? Infinity : 0 
                }}
                className="w-2 h-2 bg-blue-500 rounded-full"
              />
            )}
          </div>
        </div>

        {/* Status Messages */}
        <div ref={scrollRef} className="max-h-96 overflow-y-auto scroll-smooth" role="status" aria-live="polite">
          <AnimatePresence mode="popLayout">
            {/* Active/Processing Updates */}
            {activeUpdates.map((update, index) => {
              const isLastUpdate = index === activeUpdates.length - 1;
              const updateTimestamp = (update as any).timestamp;
              const timeDisplay = updateTimestamp 
                ? new Date(updateTimestamp).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })
                : new Date().toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  });
              
              return (
                <motion.div
                  key={`active-${index}`}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 20 }}
                  transition={{ duration: 0.3, delay: index * 0.05 }}
                  className={`px-6 py-3 border-b border-gray-100 dark:border-gray-800 last:border-b-0 ${getStatusColor(
                    update.status
                  )}`}
                >
                  <div className="flex items-start gap-3">
                    <motion.div
                      animate={
                        update.status === StatusType.PROCESSING && isLoading && isLastUpdate
                          ? { scale: [1, 1.2, 1] }
                          : {}
                      }
                      transition={{ 
                        duration: 1, 
                        repeat: isLoading && isLastUpdate ? Infinity : 0 
                      }}
                      className="mt-0.5"
                    >
                      {getStatusIcon(update.status, isLoading, isLastUpdate)}
                    </motion.div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-700 dark:text-gray-300">
                        {update.message}
                      </p>
                    </div>
                    <span className="text-xs text-gray-400 dark:text-gray-600 whitespace-nowrap">
                      {timeDisplay}
                    </span>
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>

        {/* Footer - Progress indicator */}
        {isLoading && (
          <div className="px-6 py-3 bg-gray-50 dark:bg-gray-900/50 border-t border-gray-200 dark:border-gray-800">
            <div className="flex items-center gap-2">
              <motion.div
                className="flex gap-1"
                animate={{ opacity: [0.4, 1, 0.4] }}
                transition={{ 
                  duration: 1.5, 
                  repeat: isLoading ? Infinity : 0 
                }}
              >
                <div className="w-1.5 h-1.5 bg-blue-500 rounded-full" />
                <div className="w-1.5 h-1.5 bg-purple-500 rounded-full" />
                <div className="w-1.5 h-1.5 bg-pink-500 rounded-full" />
              </motion.div>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                Processing your request...
              </span>
            </div>
          </div>
        )}
      </div>
    </motion.div>
  );
}
