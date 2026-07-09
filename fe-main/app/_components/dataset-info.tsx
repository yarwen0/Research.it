"use client";
import { motion } from "framer-motion";
import { Database, FileText, Search, X, ExternalLink, Calendar, Users as UsersIcon } from "lucide-react";
import { useState, useMemo, useEffect } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  getPaginationRowModel,
  ColumnDef,
  flexRender,
  ColumnFiltersState,
  SortingState,
} from "@tanstack/react-table";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import PieChartVisualization from "./charts/pie-chart";
import { getStoredResponses } from "@/lib/response-store";

interface DatasetPaper {
  paper_id: string;
  title: string;
  original_name_used: string;
}

interface PaperDetails {
  paper_id: string;
  title: string;
  authors?: string[];
  date?: string;
  abstract?: string;
  keywords?: string[];
  pdf_url?: string;
}

interface Dataset {
  normalized_id: string;
  original_names: string[];
  paper_count: number;
  papers: DatasetPaper[];
}

interface ChartSeries {
  id?: string;
  dataKey?: string;
  label: string;
  color?: string;
  valueKey?: string;
  valueFormatter?: string;
  stack?: string;
  stacked?: boolean;
}

interface ChartData {
  config: {
    type: "bar" | "pie" | "line";
    title: string;
    description: string;
    xAxisLabel?: string | null;
    yAxisLabel?: string | null;
    layout?: "horizontal" | "vertical" | null;
    stacked?: boolean;
  };
  dataPoints: any[];
  series: ChartSeries[];
}

interface DatasetsData {
  total_unique_datasets: number;
  datasets: Dataset[];
  pie_chart?: ChartData;
}

interface DatasetInfoProps {
  datasets: DatasetsData | null;
  processedPapers?: any[]; // Papers from the current research response
}

export default function DatasetInfo({ datasets, processedPapers = [] }: DatasetInfoProps) {
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [papersMap, setPapersMap] = useState<Map<string, PaperDetails>>(new Map());

  // Load paper details from provided processedPapers or fallback to localStorage
  useEffect(() => {
    const paperDetailsMap = new Map<string, PaperDetails>();

    console.log("📚 Loading paper details for datasets...");
    console.log("  processedPapers count:", processedPapers?.length || 0);

    // First, try to use the provided processedPapers from current response
    if (processedPapers && processedPapers.length > 0) {
      processedPapers.forEach((paper: any) => {
        if (paper.paper_id) {
          // Handle multiple possible data structures
          const title = paper.title || paper.normalized?.title || paper.extraction?.title || "Untitled Paper";
          const authors = paper.authors || paper.normalized?.authors || paper.extraction?.authors || [];
          const date = paper.published || paper.date || paper.normalized?.date || paper.extraction?.date || "";
          const abstract = paper.abstract || paper.normalized?.abstract || paper.extraction?.abstract || "";
          const keywords = paper.keywords || paper.normalized?.keywords || paper.extraction?.keywords || [];
          const pdf_url = paper.pdf_url || paper.normalized?.pdf_url || paper.extraction?.pdf_url || "";

          paperDetailsMap.set(paper.paper_id, {
            paper_id: paper.paper_id,
            title,
            authors,
            date,
            abstract,
            keywords,
            pdf_url,
          });
          
          console.log(`  ✅ Loaded paper: ${paper.paper_id} - ${title.substring(0, 50)}...`);
        }
      });
    } else {
      // Fallback: Load from all stored responses in localStorage
      console.log("  Falling back to localStorage...");
      const responses = getStoredResponses();
      responses.forEach((response) => {
        if (response.processed_papers && Array.isArray(response.processed_papers)) {
          response.processed_papers.forEach((paper: any) => {
            if (paper.paper_id) {
              // Handle multiple possible data structures
              const title = paper.title || paper.normalized?.title || paper.extraction?.title || "Untitled Paper";
              const authors = paper.authors || paper.normalized?.authors || paper.extraction?.authors || [];
              const date = paper.published || paper.date || paper.normalized?.date || paper.extraction?.date || "";
              const abstract = paper.abstract || paper.normalized?.abstract || paper.extraction?.abstract || "";
              const keywords = paper.keywords || paper.normalized?.keywords || paper.extraction?.keywords || [];
              const pdf_url = paper.pdf_url || paper.normalized?.pdf_url || paper.extraction?.pdf_url || "";

              paperDetailsMap.set(paper.paper_id, {
                paper_id: paper.paper_id,
                title,
                authors,
                date,
                abstract,
                keywords,
                pdf_url,
              });
            }
          });
        }
      });
    }

    console.log(`  📊 Total papers loaded: ${paperDetailsMap.size}`);
    setPapersMap(paperDetailsMap);
  }, [processedPapers]);

  const columns = useMemo<ColumnDef<Dataset>[]>(
    () => [
      {
        accessorKey: "normalized_id",
        header: "Dataset Name",
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <div className="font-medium text-gray-900 dark:text-gray-100">
              {row.original.normalized_id}
            </div>
            <a
              href={`https://www.google.com/search?q=${encodeURIComponent(row.original.normalized_id + " dataset")}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary hover:text-primary/80 transition-colors"
              title="Search on Google"
            >
              <ExternalLink className="w-4 h-4" />
            </a>
          </div>
        ),
      },
      {
        accessorKey: "original_names",
        header: "Aliases",
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1.5">
            {row.original.original_names.slice(0, 3).map((name, idx) => (
              <span
                key={idx}
                className="px-2 py-0.5 bg-primary/10 text-primary text-xs rounded-full"
              >
                {name}
              </span>
            ))}
            {row.original.original_names.length > 3 && (
              <span className="px-2 py-0.5 text-xs text-gray-500 dark:text-gray-400">
                +{row.original.original_names.length - 3} more
              </span>
            )}
          </div>
        ),
        enableSorting: false,
      },
      {
        accessorKey: "paper_count",
        header: "Papers",
        cell: ({ row }) => (
          <div className="text-center font-semibold text-primary">
            {row.original.paper_count}
          </div>
        ),
      },
      {
        id: "actions",
        header: "Details",
        cell: ({ row }) => {
          const isExpanded = expandedRows.has(row.original.normalized_id);
          return (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setExpandedRows((prev) => {
                  const newSet = new Set(prev);
                  if (newSet.has(row.original.normalized_id)) {
                    newSet.delete(row.original.normalized_id);
                  } else {
                    newSet.add(row.original.normalized_id);
                  }
                  return newSet;
                });
              }}
              className="text-xs"
            >
              {isExpanded ? "Hide" : "View"} Papers
            </Button>
          );
        },
      },
    ],
    [expandedRows]
  );

  const table = useReactTable({
    data: datasets?.datasets || [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    onColumnFiltersChange: setColumnFilters,
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    globalFilterFn: "includesString",
    state: {
      columnFilters,
      sorting,
      globalFilter,
    },
    initialState: {
      pagination: {
        pageSize: 10,
      },
    },
  });

  if (!datasets || !datasets.datasets || datasets.datasets.length === 0) {
    return (
      <div className="flex items-center justify-center h-[400px] bg-gray-50 dark:bg-gray-800/50 rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-700">
        <div className="text-center">
          <Database className="w-16 h-16 mx-auto mb-4 text-gray-400 dark:text-gray-600" />
          <p className="text-lg font-medium text-gray-600 dark:text-gray-400">
            No dataset information available
          </p>
          <p className="text-sm text-gray-500 dark:text-gray-500 mt-2">
            Dataset usage will be displayed here once the research analysis is complete
          </p>
        </div>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="w-full space-y-6"
    >
      {/* Summary Card */}
      <div className="bg-primary/5 rounded-lg p-6 border border-primary/30">
        <div className="flex items-center gap-3 mb-2">
          <Database className="w-6 h-6 text-primary" />
          <h3 className="text-xl font-bold text-gray-900 dark:text-gray-100">
            Dataset Overview
          </h3>
        </div>
        <p className="text-gray-700 dark:text-gray-300 text-lg">
          Found <span className="font-bold text-primary">{datasets.total_unique_datasets}</span> unique datasets across the research papers
        </p>
      </div>

      {/* Pie Chart Visualization */}
      {datasets.pie_chart && (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm p-6"
        >
          <div className="mb-4">
            <h3 className="text-lg font-bold text-gray-900 dark:text-gray-100 mb-2">
              {datasets.pie_chart.config.title}
            </h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              {datasets.pie_chart.config.description}
            </p>
          </div>
          <PieChartVisualization chart={datasets.pie_chart} />
        </motion.div>
      )}

      {/* Searchable Table */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.4 }}
        className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm p-6"
      >
        <div className="mb-6">
          <h3 className="text-lg font-bold text-gray-900 dark:text-gray-100 mb-4">
            All Datasets
          </h3>
          
          {/* Search Input */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <Input
              placeholder="Search datasets..."
              value={globalFilter ?? ""}
              onChange={(e) => setGlobalFilter(e.target.value)}
              className="pl-9 pr-9"
            />
            {globalFilter && (
              <button
                onClick={() => setGlobalFilter("")}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>

        {/* Table */}
        <div className="rounded-md border border-gray-200 dark:border-gray-700 overflow-hidden">
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <TableHead
                      key={header.id}
                      className="bg-gray-50 dark:bg-gray-900 font-semibold"
                    >
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext()
                          )}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows?.length ? (
                table.getRowModel().rows.map((row) => {
                  const isExpanded = expandedRows.has(row.original.normalized_id);
                  
                  return (
                    <>
                      <TableRow
                        key={row.id}
                        data-state={row.getIsSelected() && "selected"}
                      >
                        {row.getVisibleCells().map((cell) => (
                          <TableCell key={cell.id}>
                            {flexRender(
                              cell.column.columnDef.cell,
                              cell.getContext()
                            )}
                          </TableCell>
                        ))}
                      </TableRow>
                      
                      {/* Expanded Papers Row */}
                      {isExpanded && (
                        <TableRow key={`${row.id}-expanded`}>
                          <TableCell colSpan={columns.length} className="bg-gray-50 dark:bg-gray-900/50 p-6">
                            <div className="space-y-3">
                              <h5 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-2">
                                <FileText className="w-4 h-4" />
                                Papers using {row.original.normalized_id}:
                              </h5>
                              {row.original.papers.map((paper, paperIdx) => {
                                const paperDetails = papersMap.get(paper.paper_id);
                                
                                return (
                                  <motion.div
                                    key={paperIdx}
                                    initial={{ opacity: 0, x: -20 }}
                                    animate={{ opacity: 1, x: 0 }}
                                    transition={{ duration: 0.2, delay: paperIdx * 0.05 }}
                                    className="bg-white dark:bg-gray-800 rounded-md p-4 border border-gray-200 dark:border-gray-700"
                                  >
                                    {paperDetails ? (
                                      <div className="space-y-3">
                                        {/* Title with PDF Link */}
                                        <div className="flex items-start gap-2">
                                          <FileText className="w-4 h-4 mt-1 text-primary flex-shrink-0" />
                                          <div className="flex-1">
                                            <div className="flex items-start justify-between gap-2">
                                              <h5 className="font-semibold text-gray-900 dark:text-gray-100 leading-tight">
                                                {paperDetails.title}
                                              </h5>
                                              {paperDetails.pdf_url && (
                                                <a
                                                  href={paperDetails.pdf_url}
                                                  target="_blank"
                                                  rel="noopener noreferrer"
                                                  className="flex-shrink-0 p-1 text-primary hover:bg-primary/10 rounded transition-colors"
                                                  title="View PDF"
                                                >
                                                  <ExternalLink className="w-4 h-4" />
                                                </a>
                                              )}
                                            </div>
                                            <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400 mt-1">
                                              <span className="font-mono bg-gray-100 dark:bg-gray-700 px-2 py-0.5 rounded">
                                                {paper.paper_id}
                                              </span>
                                              <span>•</span>
                                              <span className="italic">
                                                Referenced as: &quot;{paper.original_name_used}&quot;
                                              </span>
                                            </div>
                                          </div>
                                        </div>

                                        {/* Authors */}
                                        {paperDetails.authors && paperDetails.authors.length > 0 && (
                                          <div className="flex items-start gap-2">
                                            <UsersIcon className="w-4 h-4 mt-0.5 text-gray-500 dark:text-gray-400 flex-shrink-0" />
                                            <p className="text-sm text-gray-600 dark:text-gray-400">
                                              {paperDetails.authors.slice(0, 3).join(", ")}
                                              {paperDetails.authors.length > 3 && ` +${paperDetails.authors.length - 3} more`}
                                            </p>
                                          </div>
                                        )}

                                        {/* Date */}
                                        {paperDetails.date && (
                                          <div className="flex items-center gap-2">
                                            <Calendar className="w-4 h-4 text-gray-500 dark:text-gray-400 flex-shrink-0" />
                                            <p className="text-sm text-gray-600 dark:text-gray-400">
                                              {new Date(paperDetails.date).toLocaleDateString('en-US', {
                                                year: 'numeric',
                                                month: 'long',
                                                day: 'numeric'
                                              })}
                                            </p>
                                          </div>
                                        )}

                                        {/* Keywords */}
                                        {paperDetails.keywords && paperDetails.keywords.length > 0 && (
                                          <div className="flex flex-wrap gap-1.5">
                                            {paperDetails.keywords.slice(0, 5).map((keyword, kIndex) => (
                                              <span
                                                key={kIndex}
                                                className="px-2 py-0.5 bg-primary/10 text-primary text-xs rounded-full font-medium"
                                              >
                                                {keyword}
                                              </span>
                                            ))}
                                            {paperDetails.keywords.length > 5 && (
                                              <span className="px-2 py-0.5 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 text-xs rounded-full font-medium">
                                                +{paperDetails.keywords.length - 5}
                                              </span>
                                            )}
                                          </div>
                                        )}

                                        {/* Abstract Preview */}
                                        {paperDetails.abstract && (
                                          <div className="pt-2 border-t border-gray-200 dark:border-gray-700">
                                            <p className="text-sm text-gray-600 dark:text-gray-400 line-clamp-3">
                                              {paperDetails.abstract}
                                            </p>
                                          </div>
                                        )}
                                      </div>
                                    ) : (
                                      <div className="flex items-start gap-3">
                                        <FileText className="w-4 h-4 mt-1 flex-shrink-0 text-primary" />
                                        <div className="flex-1 min-w-0">
                                          <p className="font-medium text-gray-900 dark:text-gray-100 mb-1">
                                            {paper.title}
                                          </p>
                                          <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                                            <span className="font-mono bg-gray-100 dark:bg-gray-700 px-2 py-0.5 rounded">
                                              {paper.paper_id}
                                            </span>
                                            <span>•</span>
                                            <span className="italic">
                                              Referenced as: &quot;{paper.original_name_used}&quot;
                                            </span>
                                            <span className="ml-2 text-gray-400">(details not available)</span>
                                          </div>
                                        </div>
                                      </div>
                                    )}
                                  </motion.div>
                                );
                              })}
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </>
                  );
                })
              ) : (
                <TableRow>
                  <TableCell
                    colSpan={columns.length}
                    className="h-24 text-center text-gray-500 dark:text-gray-400"
                  >
                    No datasets found.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between mt-4">
          <div className="text-sm text-gray-600 dark:text-gray-400">
            Showing {table.getState().pagination.pageIndex * table.getState().pagination.pageSize + 1} to{" "}
            {Math.min(
              (table.getState().pagination.pageIndex + 1) * table.getState().pagination.pageSize,
              table.getFilteredRowModel().rows.length
            )}{" "}
            of {table.getFilteredRowModel().rows.length} datasets
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
            >
              Next
            </Button>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}
