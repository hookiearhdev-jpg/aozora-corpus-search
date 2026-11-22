import Encoding from "encoding-japanese";
import { COLUMN_DEFINITIONS, type ColumnKey, type KwicRow } from "../types/corpus";

export type ExportFormat = "csv" | "tsv";
export type ExportEncoding = "utf8-bom" | "sjis";

export interface ExportOptions {
  format: ExportFormat;
  encoding: ExportEncoding;
  baseFilename?: string;
}

function escapeDelimitedCell(value: unknown, delimiter: "," | "\t"): string {
  if (value === null || value === undefined) {
    return "";
  }
  const str = String(value);
  const needsQuote =
    delimiter === "," ? /[",\r\n]/.test(str) : /[\t"\r\n]/.test(str);
  if (needsQuote) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

/**
 * 検索結果から指定フォーマット（CSV/TSV）・文字コード（UTF-8 BOM付 / Shift-JIS）の
 * バイト配列・MIMEタイプ・ファイル名を生成する。
 */
export function buildKwicExportPayload(
  rows: KwicRow[],
  visibleColumns: ColumnKey[],
  options: ExportOptions
): { bytes: Uint8Array; mimeType: string; filename: string } {
  const { format, encoding, baseFilename = "aozora_kwic_results" } = options;
  const delimiter: "," | "\t" = format === "tsv" ? "\t" : ",";

  const colOrder: ColumnKey[] = [...visibleColumns];
  // コンプライアンス要件に従い、図書カードURL列も必ず含める
  if (!colOrder.includes("card_url")) {
    colOrder.push("card_url");
  }

  const labelMap = new Map(COLUMN_DEFINITIONS.map((c) => [c.key, c.label]));
  const header = colOrder
    .map((k) => escapeDelimitedCell(labelMap.get(k) ?? k, delimiter))
    .join(delimiter);

  const bodyLines = rows.map((row) =>
    colOrder
      .map((k) => escapeDelimitedCell(row[k], delimiter))
      .join(delimiter)
  );

  const rawText = [header, ...bodyLines].join("\r\n");
  const baseMime =
    format === "tsv" ? "text/tab-separated-values" : "text/csv";
  const filename = `${baseFilename}.${format}`;

  if (encoding === "sjis") {
    const unicodeCodes = Encoding.stringToCode(rawText);
    // Shift-JIS に存在しない外字・補助漢字等は仕様通り '?' へ安全に代替される
    const sjisCodes = Encoding.convert(unicodeCodes, {
      to: "SJIS",
      from: "UNICODE",
    });
    return {
      bytes: new Uint8Array(sjisCodes),
      mimeType: `${baseMime};charset=shift_jis;`,
      filename,
    };
  }

  // UTF-8 (BOM付き: 先頭 \uFEFF)
  const utf8WithBom = "\uFEFF" + rawText;
  return {
    bytes: new TextEncoder().encode(utf8WithBom),
    mimeType: `${baseMime};charset=utf-8;`,
    filename,
  };
}

/**
 * 検索結果を指定のフォーマット・文字コードでクライアントサイドダウンロードする。
 */
export function downloadKwicFile(
  rows: KwicRow[],
  visibleColumns: ColumnKey[],
  options: ExportOptions
): void {
  const { bytes, mimeType, filename } = buildKwicExportPayload(
    rows,
    visibleColumns,
    options
  );
  const blobBytes = new Uint8Array(bytes.byteLength);
  blobBytes.set(bytes);
  const blob = new Blob([blobBytes], { type: mimeType });
  const url = URL.createObjectURL(blob);

  const link = document.createElement("a");
  link.href = url;
  link.setAttribute("download", filename);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/** 後方互換用ラッパー（UTF-8 BOM付 CSV） */
export function downloadKwicCsv(
  rows: KwicRow[],
  visibleColumns: ColumnKey[],
  filename = "aozora_kwic_results.csv"
): void {
  const baseFilename = filename.replace(/\.csv$/i, "");
  downloadKwicFile(rows, visibleColumns, {
    format: "csv",
    encoding: "utf8-bom",
    baseFilename,
  });
}
