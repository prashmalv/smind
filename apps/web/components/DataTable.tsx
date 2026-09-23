"use client";

import { count, money, percent } from "@/lib/api";

type Column = {
  key: string;
  label: string;
  format?: "text" | "currency" | "number" | "percent" | "decimal";
};

/**
 * Numeric columns are right-aligned with tabular numerals so the digits line up —
 * the single thing that makes a table of figures scannable.
 */
export function DataTable({
  columns, rows, currency = "INR", empty = "No rows for this period.",
}: {
  columns: Column[];
  rows: Record<string, unknown>[];
  currency?: string;
  empty?: string;
}) {
  if (!rows || rows.length === 0) {
    return <p className="hint">{empty}</p>;
  }

  const render = (value: unknown, format?: Column["format"]) => {
    if (value === null || value === undefined || value === "") return "—";
    const n = typeof value === "number" ? value : Number(value);
    switch (format) {
      case "currency": return money(n, currency);
      case "number": return count(n, currency);
      case "percent": return percent(n);
      case "decimal": return Number.isFinite(n) ? n.toFixed(2) : String(value);
      default: return String(value);
    }
  };

  const isNum = (f?: Column["format"]) => f && f !== "text";

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={isNum(c.format) ? "num" : undefined}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.key} className={isNum(c.format) ? "num" : undefined}>
                  {render(row[c.key], c.format)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
