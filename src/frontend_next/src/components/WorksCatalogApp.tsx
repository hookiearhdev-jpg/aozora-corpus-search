"use client";

import React, { useCallback, useEffect, useState } from "react";
import { API_BASE_URL, fetchCorpusStats, fetchWorks } from "../lib/api";
import type {
  CorpusStats,
  SortOrder,
  WorksListResponse,
  WorksSortBy,
} from "../types/corpus";
import { AppFooter } from "./AppFooter";
import { AppHeader } from "./AppHeader";

export function WorksCatalogApp() {
  const [stats, setStats] = useState<CorpusStats | null>(null);

  // 検索・フィルタ・ソート・ページネーション状態
  const [searchInput, setSearchInput] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [subcorpus, setSubcorpus] = useState("");
  const [sortBy, setSortBy] = useState<WorksSortBy>("book_id");
  const [sortOrder, setSortOrder] = useState<SortOrder>("asc");
  const [pageSize, setPageSize] = useState(100);
  const [page, setPage] = useState(1);

  const [data, setData] = useState<WorksListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 統計情報の取得
  useEffect(() => {
    let active = true;
    fetchCorpusStats()
      .then((res) => {
        if (active) setStats(res);
      })
      .catch(() => {
        // works 取得側のエラー表示に集約
      });
    return () => {
      active = false;
    };
  }, []);

  // テキスト入力のデバウンス（250ms）
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(searchInput.trim());
      setPage(1);
    }, 250);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const loadWorks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const offset = (page - 1) * pageSize;
      const res = await fetchWorks({
        q: debouncedQuery,
        subcorpus,
        sort_by: sortBy,
        sort_order: sortOrder,
        limit: pageSize,
        offset,
      });
      setData(res);
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "収録作品一覧の取得に失敗しました"
      );
    } finally {
      setLoading(false);
    }
  }, [debouncedQuery, subcorpus, sortBy, sortOrder, page, pageSize]);

  useEffect(() => {
    void loadWorks();
  }, [loadWorks]);

  const totalCount = data?.total_count ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const startNo = totalCount === 0 ? 0 : (page - 1) * pageSize + 1;
  const endNo = Math.min(page * pageSize, totalCount);

  const handleImmediateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setDebouncedQuery(searchInput.trim());
    setPage(1);
  };

  const handleResetFilters = () => {
    setSearchInput("");
    setDebouncedQuery("");
    setSubcorpus("");
    setSortBy("book_id");
    setSortOrder("asc");
    setPage(1);
  };

  return (
    <div className="min-h-screen bg-[#f7f8fa] text-slate-900 flex flex-col">
      <AppHeader
        stats={stats}
        subtitle="コーパスに収録されている青空文庫パブリックドメイン作品（著作権フラグ「なし」）の全書誌カタログ"
      />

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:px-8 space-y-5">
        {/* 検索フィルター・ソートコントロール */}
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs">
          <form onSubmit={handleImmediateSubmit} className="space-y-3">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-12">
              <div className="md:col-span-5">
                <label
                  htmlFor="works-search-input"
                  className="mb-1 block text-xs font-semibold text-slate-700"
                >
                  作品名・著者名で絞り込み（部分一致）
                </label>
                <div className="flex gap-2">
                  <input
                    id="works-search-input"
                    type="text"
                    value={searchInput}
                    onChange={(e) => setSearchInput(e.target.value)}
                    placeholder="例: 夏目漱石, 坊っちゃん, 芥川, 銀河鉄道"
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
                  />
                  <button
                    type="submit"
                    className="shrink-0 rounded-lg bg-indigo-700 px-4 py-2 text-xs font-bold text-white hover:bg-indigo-800 transition"
                  >
                    検索
                  </button>
                </div>
              </div>

              <div className="md:col-span-2">
                <label
                  htmlFor="works-subcorpus"
                  className="mb-1 block text-xs font-semibold text-slate-700"
                >
                  文字遣い種別
                </label>
                <select
                  id="works-subcorpus"
                  value={subcorpus}
                  onChange={(e) => {
                    setSubcorpus(e.target.value);
                    setPage(1);
                  }}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
                >
                  <option value="">（すべて）</option>
                  {(stats?.subcorpora ?? [
                    "新字新仮名",
                    "新字旧仮名",
                    "旧字旧仮名",
                    "旧字新仮名",
                    "その他",
                  ]).map((sc) => (
                    <option key={sc} value={sc}>
                      {sc}
                    </option>
                  ))}
                </select>
              </div>

              <div className="md:col-span-3">
                <label
                  htmlFor="works-sort"
                  className="mb-1 block text-xs font-semibold text-slate-700"
                >
                  並び順
                </label>
                <div className="flex gap-1.5">
                  <select
                    id="works-sort"
                    value={sortBy}
                    onChange={(e) => {
                      setSortBy(e.target.value as WorksSortBy);
                      setPage(1);
                    }}
                    className="flex-1 rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-sm focus:border-indigo-500 focus:outline-none"
                  >
                    <option value="book_id">作品ID</option>
                    <option value="author">著者名</option>
                    <option value="title">作品名</option>
                    <option value="published_year">初出年</option>
                  </select>
                  <select
                    aria-label="昇順・降順"
                    value={sortOrder}
                    onChange={(e) => {
                      setSortOrder(e.target.value as SortOrder);
                      setPage(1);
                    }}
                    className="w-20 rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm focus:border-indigo-500 focus:outline-none"
                  >
                    <option value="asc">昇順</option>
                    <option value="desc">降順</option>
                  </select>
                </div>
              </div>

              <div className="md:col-span-2">
                <label
                  htmlFor="works-page-size"
                  className="mb-1 block text-xs font-semibold text-slate-700"
                >
                  表示件数
                </label>
                <select
                  id="works-page-size"
                  value={pageSize}
                  onChange={(e) => {
                    setPageSize(Number(e.target.value));
                    setPage(1);
                  }}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
                >
                  {[50, 100, 200, 500, 1000].map((n) => (
                    <option key={n} value={n}>
                      {n} 件 / ページ
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {(searchInput || subcorpus || sortBy !== "book_id" || sortOrder !== "asc") && (
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={handleResetFilters}
                  className="text-xs font-medium text-indigo-700 hover:text-indigo-900 hover:underline"
                >
                  絞り込み・並び順をリセット
                </button>
              </div>
            )}
          </form>
        </section>

        {error && (
          <div
            role="alert"
            className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800"
          >
            <strong>取得エラー:</strong> {error}
            <div className="mt-1 text-xs text-rose-600">
              FastAPI サーバー（<code>{API_BASE_URL}</code>）の起動状態をご確認ください。
            </div>
          </div>
        )}

        {/* 件数サマリ ＆ 上部ページネーション */}
        <section className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-5 py-3.5 shadow-xs">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="rounded-lg bg-emerald-50 px-3 py-1.5 text-sm font-bold text-emerald-800 ring-1 ring-emerald-200 tabular-nums">
              {debouncedQuery || subcorpus
                ? `該当作品数: ${totalCount.toLocaleString()} 件`
                : `全収録作品数: ${totalCount.toLocaleString()} 件`}
            </span>
            <span className="rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700 tabular-nums">
              {totalCount > 0
                ? `${startNo.toLocaleString()} 〜 ${endNo.toLocaleString()} 件目を表示中`
                : "0 件"}
            </span>
            {loading && (
              <span className="text-xs font-medium text-indigo-600">読み込み中...</span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={loading || page <= 1}
              onClick={() => setPage(1)}
              className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"
            >
              « 最初
            </button>
            <button
              type="button"
              disabled={loading || page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"
            >
              ← 前へ
            </button>
            <span className="px-2 text-xs font-semibold text-slate-700 tabular-nums">
              {page.toLocaleString()} / {totalPages.toLocaleString()} ページ
            </span>
            <button
              type="button"
              disabled={loading || page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"
            >
              次へ →
            </button>
            <button
              type="button"
              disabled={loading || page >= totalPages}
              onClick={() => setPage(totalPages)}
              className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"
            >
              最後 »
            </button>
          </div>
        </section>

        {/* データテーブル */}
        <section className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-xs">
          {!loading && data && data.items.length === 0 ? (
            <div className="p-12 text-center text-sm text-slate-500">
              条件に一致する収録作品は見つかりませんでした。
            </div>
          ) : (
            <table className="w-full border-collapse text-sm text-slate-800">
              <thead>
                <tr className="border-b-2 border-slate-200 bg-slate-100/90 text-xs font-semibold text-slate-700">
                  <th className="px-4 py-3 text-right text-slate-500 whitespace-nowrap">#</th>
                  <th className="px-4 py-3 text-right whitespace-nowrap">作品ID</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">作品名（図書カードリンク）</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">著者名</th>
                  <th className="px-4 py-3 text-right whitespace-nowrap">初出年</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">NDC</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">文字遣い</th>
                  <th className="px-4 py-3 text-center whitespace-nowrap">出典</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(data?.items ?? []).map((item, idx) => (
                  <tr
                    key={item.book_id}
                    className="transition-colors hover:bg-indigo-50/35"
                  >
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-slate-400 tabular-nums whitespace-nowrap">
                      {startNo + idx}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-slate-500 tabular-nums whitespace-nowrap">
                      {String(item.book_id).padStart(6, "0")}
                    </td>
                    <td className="px-4 py-2.5 font-medium">
                      {item.card_url ? (
                        <a
                          href={item.card_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-indigo-700 hover:text-indigo-900 hover:underline"
                          title="青空文庫 図書カードを新しいタブで開く"
                        >
                          {item.title}
                        </a>
                      ) : (
                        <span>{item.title}</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-slate-700 whitespace-nowrap">
                      {item.author}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-slate-700 tabular-nums whitespace-nowrap">
                      {item.published_year ?? "-"}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-slate-600 whitespace-nowrap">
                      {item.ndc || "-"}
                    </td>
                    <td className="px-4 py-2.5 whitespace-nowrap">
                      <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-700">
                        {item.subcorpus || "-"}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-center whitespace-nowrap">
                      {item.card_url ? (
                        <a
                          href={item.card_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 rounded border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700 hover:bg-indigo-100"
                        >
                          図書カード ↗
                        </a>
                      ) : (
                        <span className="text-slate-300">-</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {/* 下部ページネーション */}
        {totalPages > 1 && (
          <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
            <button
              type="button"
              disabled={loading || page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"
            >
              ← 前のページ
            </button>
            <span className="px-3 text-xs font-semibold text-slate-600 tabular-nums">
              {page.toLocaleString()} / {totalPages.toLocaleString()} ページ
            </span>
            <button
              type="button"
              disabled={loading || page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"
            >
              次のページ →
            </button>
          </div>
        )}
      </main>

      <AppFooter />
    </div>
  );
}
