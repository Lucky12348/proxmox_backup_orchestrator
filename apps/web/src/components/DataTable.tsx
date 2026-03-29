import type { ReactNode } from "react";

interface DataTableProps {
  children: ReactNode;
}

export function DataTable({ children }: DataTableProps) {
  return <div className="data-table-wrap">{children}</div>;
}
