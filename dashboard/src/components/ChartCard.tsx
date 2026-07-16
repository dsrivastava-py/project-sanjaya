// Card wrapper giving every chart its mandatory table-view toggle (§4.3).
// Chart children render by default; the toggle swaps in an accessible table.
import { useState, type ReactNode } from "react";

import { Card, IconButton } from "./ui";

export interface TableSpec {
  columns: string[];
  rows: (string | number)[][];
}

export function ChartCard({
  title,
  table,
  actions,
  children,
  className = "",
}: {
  title: ReactNode;
  table: TableSpec;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const [showTable, setShowTable] = useState(false);
  return (
    <Card
      title={title}
      className={className}
      actions={
        <>
          {actions}
          <IconButton
            label={showTable ? "Show chart" : "Show table"}
            active={showTable}
            onClick={() => setShowTable((v) => !v)}
          >
            {showTable ? "◫ Chart" : "▤ Table"}
          </IconButton>
        </>
      }
    >
      {showTable ? <DataTable spec={table} /> : children}
    </Card>
  );
}

export function DataTable({ spec }: { spec: TableSpec }) {
  if (spec.rows.length === 0)
    return <p className="py-6 text-center text-[13px] text-ink3">No data.</p>;
  return (
    <div className="max-h-80 overflow-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-hairline text-left text-ink3">
            {spec.columns.map((c) => (
              <th key={c} className="py-1.5 pr-4 font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {spec.rows.map((r, i) => (
            <tr key={i} className="border-b border-hairline last:border-0">
              {r.map((v, k) => (
                <td key={k} className={`py-1.5 pr-4 ${k > 0 ? "tnum" : ""} text-ink2`}>
                  {v}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
