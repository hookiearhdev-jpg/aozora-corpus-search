"use client";

import React from "react";
import {
  COLUMN_DEFINITIONS,
  type ColumnKey,
  type KwicRow,
} from "../types/corpus";

interface KwicTableProps {
  items: KwicRow[];
  visibleColumns: ColumnKey[];
  onToggleColumn: (key: ColumnKey) => void;
  onResetColumns: () => void;
  startIndex: number;
}

export function KwicTable({
  items,
  visibleColumns,
  onToggleColumn,
  onResetColumns,
  startIndex,
}: KwicTableProps) {
  const orderedCols = COLUMN_DEFINITIONS.filter((c) =>
    visibleColumns.includes(c.key)
  );

  return (
    <div className="space-y-3">
      {/* 列の表示切り替えパネル */}
      <div className="rounded-xl border border-slate-200 bg-slate-50/80 p-3.5">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-semibold tracking-wide text-slate-600">
            表示列の切り替え（{orderedCols.length} / {COLUMN_DEFINITIONS.length} 列）
          </span>
          <button
            type="button"
            onClick={onResetColumns}
            className="text-xs font-medium text-indigo-700 hover:text-indigo-900 hover:underline"
          >
            初期表示に戻す
          </button>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {COLUMN_DEFINITIONS.map((col) => {
            const active = visibleColumns.includes(col.key);
            return (
              <button
                key={col.key}
                type="button"
                onClick={() => onToggleColumn(col.key)}
                aria-pressed={active}
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition ${
                  active
                    ? "border-indigo-600 bg-indigo-600 text-white shadow-xs"
                    : "border-slate-300 bg-white text-slate-600 hover:border-slate-400 hover:bg-slate-100"
                }`}
              >
                <span className="text-[10px]">{active ? "✓" : "+"}</span>
                {col.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* KWIC テーブル本体 */}
      {orderedCols.length === 0 ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-center text-sm text-amber-800">
          表示する列を1つ以上選択してください。
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-slate-200 bg-white p-10 text-center text-sm text-slate-500">
          条件に一致する用例は見つかりませんでした。
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-xs">
          <table className="w-full border-collapse text-sm text-slate-800">
            <thead>
              <tr className="border-b-2 border-slate-200 bg-slate-100/90 text-xs font-semibold text-slate-700">
                <th className="sticky top-0 bg-slate-100/95 px-3 py-2.5 text-right text-slate-500 whitespace-nowrap">
                  #
                </th>
                {orderedCols.map((col) => {
                  let alignClass = "text-left";
                  let extraClass = "";
                  if (col.key === "left_context") {
                    alignClass = "text-right pr-2";
                  } else if (col.key === "key_text") {
                    alignClass = "text-center";
                    extraClass = "text-rose-700 bg-rose-50/90 border-x border-rose-200";
                  } else if (col.key === "right_context") {
                    alignClass = "text-left pl-2";
                  }
                  return (
                    <th
                      key={col.key}
                      className={`sticky top-0 bg-slate-100/95 px-3 py-2.5 whitespace-nowrap ${alignClass} ${extraClass}`}
                    >
                      {col.label}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((row, idx) => (
                <tr
                  key={`${row.sentence_id}-${row.token_index}-${idx}`}
                  className="transition-colors hover:bg-indigo-50/35"
                  title={row.text}
                >
                  <td className="px-3 py-2 text-right font-mono text-xs text-slate-400 whitespace-nowrap tabular-nums">
                    {startIndex + idx + 1}
                  </td>
                  {orderedCols.map((col) => {
                    if (col.key === "title") {
                      return (
                        <td key={col.key} className="px-3 py-2 whitespace-nowrap">
                          {row.card_url ? (
                            <a
                              href={row.card_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="font-medium text-indigo-700 hover:text-indigo-900 hover:underline"
                              title="青空文庫 図書カードを新しいタブで開く"
                            >
                              {row.title}
                            </a>
                          ) : (
                            <span>{row.title}</span>
                          )}
                        </td>
                      );
                    }
                    if (col.key === "card_url") {
                      return (
                        <td key={col.key} className="px-3 py-2 whitespace-nowrap">
                          {row.card_url ? (
                            <a
                              href={row.card_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 rounded border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700 hover:bg-indigo-100"
                            >
                              図書カード ↗
                            </a>
                          ) : (
                            <span className="text-slate-400">-</span>
                          )}
                        </td>
                      );
                    }
                    if (col.key === "left_context") {
                      return (
                        <td
                          key={col.key}
                          className="py-2 pl-4 pr-2 text-right font-sans text-[13.5px] text-slate-600 whitespace-nowrap"
                        >
                          {row.left_context}
                        </td>
                      );
                    }
                    if (col.key === "key_text") {
                      return (
                        <td
                          key={col.key}
                          className="border-x border-rose-200/80 bg-rose-50/75 px-3 py-2 text-center font-bold text-rose-700 whitespace-nowrap"
                        >
                          {row.key_text}
                        </td>
                      );
                    }
                    if (col.key === "right_context") {
                      return (
                        <td
                          key={col.key}
                          className="py-2 pl-2 pr-4 text-left font-sans text-[13.5px] text-slate-600 whitespace-nowrap"
                        >
                          {row.right_context}
                        </td>
                      );
                    }
                    if (col.key === "text") {
                      return (
                        <td
                          key={col.key}
                          className="min-w-[320px] max-w-[520px] px-3 py-2 text-xs leading-relaxed text-slate-700 whitespace-normal"
                        >
                          {row.text}
                        </td>
                      );
                    }
                    const val = row[col.key];
                    return (
                      <td
                        key={col.key}
                        className="px-3 py-2 text-xs text-slate-700 whitespace-nowrap"
                      >
                        {val === null || val === undefined || val === "" ? (
                          <span className="text-slate-300">-</span>
                        ) : (
                          String(val)
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
