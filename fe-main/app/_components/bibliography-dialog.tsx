"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  ColumnDef,
  SortingState,
} from "@tanstack/react-table";
import { BookOpen, ExternalLink, ArrowUpDown } from "lucide-react";
import { Input } from "@/components/ui/input";

interface BibliographyEntry {
  title: string;
  authors?: string[];
  year?: number;
  doi?: string;
  url?: string;
  journal?: string;
  venue?: string;
}

interface BibliographyDialogProps {
  bibliography: BibliographyEntry[];
}

export function BibliographyDialog({ bibliography }: BibliographyDialogProps) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState("");

  const columns: ColumnDef<BibliographyEntry>[] = [
    {
      accessorKey: "title",
      header: ({ column }) => {
        return (
          <button
            className="flex items-center gap-2 font-semibold hover:text-blue-600"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            Title
            <ArrowUpDown className="h-4 w-4" />
          </button>
        );
      },
      cell: ({ row }) => {
        const title = row.getValue("title") as string;
        const url = row.original.url || row.original.doi;
        
        return (
          <div className="flex items-start gap-2">
            <span className="flex-1 line-clamp-2">{title}</span>
            {url && (
              <a
                href={url.startsWith("http") ? url : `https://doi.org/${url}`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex-shrink-0 text-blue-600 hover:text-blue-800"
                onClick={(e) => e.stopPropagation()}
              >
                <ExternalLink className="h-4 w-4" />
              </a>
            )}
          </div>
        );
      },
    },
    {
      accessorKey: "authors",
      header: ({ column }) => {
        return (
          <button
            className="flex items-center gap-2 font-semibold hover:text-blue-600"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            Authors
            <ArrowUpDown className="h-4 w-4" />
          </button>
        );
      },
      cell: ({ row }) => {
        const authors = row.getValue("authors") as string[] | undefined;
        if (!authors || authors.length === 0) return <span className="text-gray-400">N/A</span>;
        
        const displayAuthors = authors.slice(0, 3).join(", ");
        const remaining = authors.length - 3;
        
        return (
          <span className="text-sm">
            {displayAuthors}
            {remaining > 0 && <span className="text-gray-500"> +{remaining} more</span>}
          </span>
        );
      },
      filterFn: (row, id, value) => {
        const authors = row.getValue(id) as string[] | undefined;
        if (!authors) return false;
        return authors.some(author => 
          author.toLowerCase().includes(value.toLowerCase())
        );
      },
    },
    {
      accessorKey: "year",
      header: ({ column }) => {
        return (
          <button
            className="flex items-center gap-2 font-semibold hover:text-blue-600"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            Year
            <ArrowUpDown className="h-4 w-4" />
          </button>
        );
      },
      cell: ({ row }) => {
        const year = row.getValue("year") as number | undefined;
        return year ? <span>{year}</span> : <span className="text-gray-400">N/A</span>;
      },
    },
  ];

  const table = useReactTable({
    data: bibliography,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    state: {
      sorting,
      globalFilter,
    },
  });

  return (
    <Dialog>
      <DialogTrigger asChild>
        <button className="px-3 py-1 text-xs bg-blue-100 hover:bg-blue-200 text-blue-700 rounded flex items-center gap-1 transition-colors">
          <BookOpen className="w-3 h-3" />
          View Bibliography ({bibliography.length})
        </button>
      </DialogTrigger>
      <DialogContent className="max-w-5xl max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Bibliography</DialogTitle>
          <DialogDescription>
            {bibliography.length} references cited in this review
          </DialogDescription>
        </DialogHeader>
        
        <div className="flex flex-col gap-4 flex-1 min-h-0">
          {/* Search Input */}
          <Input
            placeholder="Search by title, authors, year, or venue..."
            value={globalFilter ?? ""}
            onChange={(e) => setGlobalFilter(e.target.value)}
            className="max-w-sm"
          />

          {/* Table */}
          <div className="flex-1 overflow-auto border rounded-lg">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0 z-10">
                {table.getHeaderGroups().map((headerGroup) => (
                  <tr key={headerGroup.id} className="border-b">
                    {headerGroup.headers.map((header) => (
                      <th
                        key={header.id}
                        className="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider"
                      >
                        {header.isPlaceholder
                          ? null
                          : flexRender(
                              header.column.columnDef.header,
                              header.getContext()
                            )}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {table.getRowModel().rows.length === 0 ? (
                  <tr>
                    <td
                      colSpan={columns.length}
                      className="px-4 py-8 text-center text-gray-500"
                    >
                      No results found
                    </td>
                  </tr>
                ) : (
                  table.getRowModel().rows.map((row) => (
                    <tr
                      key={row.id}
                      className="hover:bg-gray-50 transition-colors"
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} className="px-4 py-3">
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext()
                          )}
                        </td>
                      ))}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Footer with count */}
          <div className="text-sm text-gray-600">
            Showing {table.getFilteredRowModel().rows.length} of {bibliography.length} entries
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
