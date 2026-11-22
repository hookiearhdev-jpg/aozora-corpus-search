"use client";

import React, { useEffect, useRef, useState } from "react";
import { API_BASE_URL, fetchCorpusStats, searchCorpus } from "../lib/api";
import {
  downloadKwicFile,
  type ExportEncoding,
  type ExportFormat,
} from "../lib/csv";
import {
  DEFAULT_VISIBLE_COLUMNS,
  createEmptyTokenCondition,
  type CollocationItem,
  type CollocationRequest,
  type ColumnKey,
  type CorpusStats,
  type Direction,
  type MatchMode,
  type SearchRequest,
  type SearchResponse,
  type TokenCondition,
} from "../types/corpus";
import { AppFooter } from "./AppFooter";
import { AppHeader } from "./AppHeader";
import { KwicTable } from "./KwicTable";

const MATCH_MODE_OPTIONS: { value: MatchMode; label: string }[] = [
  { value: "exact", label: "完全一致" },
  { value: "prefix", label: "前方一致" },
  { value: "contains", label: "部分一致" },
  { value: "regex", label: "正規表現" },
];

export function CorpusSearchApp() {
  const [stats, setStats] = useState<CorpusStats | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);

  // キー（中心語）条件
  const [keyCond, setKeyCond] = useState<TokenCondition>(createEmptyTokenCondition);

  // 共起条件（動的増減）
  const nextCollocIdRef = useRef(1);
  const [collocations, setCollocations] = useState<CollocationItem[]>([]);

  // 書誌フィルタ・検索オプション
  const [showBibFilter, setShowBibFilter] = useState(false);
  const [titleQuery, setTitleQuery] = useState("");
  const [authorQuery, setAuthorQuery] = useState("");
  const [selectedSubcorpus, setSelectedSubcorpus] = useState("");
  const [ndcPrefix, setNdcPrefix] = useState("");
  const [pubYearMin, setPubYearMin] = useState("");
  const [pubYearMax, setPubYearMax] = useState("");
  const [pageSize, setPageSize] = useState(50);
  const [contextChars, setContextChars] = useState(30);

  // 検索状態・結果
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [lastPayload, setLastPayload] = useState<SearchRequest | null>(null);
  const [showSql, setShowSql] = useState(false);

  // 表示列選択
  const [visibleColumns, setVisibleColumns] = useState<ColumnKey[]>(
    DEFAULT_VISIBLE_COLUMNS
  );

  // エクスポート設定（フォーマット / 文字コード）
  const [exportFormat, setExportFormat] = useState<ExportFormat>("csv");
  const [exportEncoding, setExportEncoding] =
    useState<ExportEncoding>("utf8-bom");

  useEffect(() => {
    let active = true;
    fetchCorpusStats()
      .then((data) => {
        if (active) {
          setStats(data);
          setStatsError(null);
        }
      })
      .catch((err: unknown) => {
        if (active) {
          setStatsError(
            err instanceof Error ? err.message : "統計情報の取得に失敗しました"
          );
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const updateKeyField = <K extends keyof TokenCondition>(
    field: K,
    value: TokenCondition[K]
  ) => {
    setKeyCond((prev) => ({ ...prev, [field]: value }));
  };

  const addCollocation = (direction: Direction) => {
    const id = nextCollocIdRef.current++;
    setCollocations((prev) => [
      ...prev,
      {
        id,
        direction,
        distanceType: "adjacent",
        distance: 1,
        showAdvanced: false,
        condition: createEmptyTokenCondition(),
      },
    ]);
  };

  const removeCollocation = (id: number) => {
    setCollocations((prev) => prev.filter((item) => item.id !== id));
  };

  const updateCollocation = (
    id: number,
    updater: (item: CollocationItem) => CollocationItem
  ) => {
    setCollocations((prev) =>
      prev.map((item) => (item.id === id ? updater(item) : item))
    );
  };

  const applyPreset = (preset: "before2_pos_hashiru" | "verb_te" | "single_hashiru") => {
    setSearchError(null);
    if (preset === "single_hashiru") {
      setKeyCond({
        ...createEmptyTokenCondition(),
        lemma: "走る",
        pos: "動詞",
      });
      setCollocations([]);
    } else if (preset === "before2_pos_hashiru") {
      setKeyCond({
        ...createEmptyTokenCondition(),
        lemma: "走る",
        pos: "動詞",
      });
      const id = nextCollocIdRef.current++;
      setCollocations([
        {
          id,
          direction: "before",
          distanceType: "exact",
          distance: 2,
          showAdvanced: false,
          condition: { ...createEmptyTokenCondition(), pos: "助詞" },
        },
      ]);
    } else if (preset === "verb_te") {
      setKeyCond({
        ...createEmptyTokenCondition(),
        pos: "動詞-一般",
        cform: "連用形",
      });
      const id = nextCollocIdRef.current++;
      setCollocations([
        {
          id,
          direction: "after",
          distanceType: "adjacent",
          distance: 1,
          showAdvanced: false,
          condition: {
            ...createEmptyTokenCondition(),
            lemma: "て",
            pos: "助詞",
          },
        },
      ]);
    }
  };

  const buildRequestPayload = (offset = 0): SearchRequest => {
    const collocRequests: CollocationRequest[] = collocations.map((c) => ({
      direction: c.direction,
      distance: c.distanceType === "adjacent" ? 1 : c.distance,
      distance_mode: c.distanceType === "within" ? "within" : "exact",
      condition: c.condition,
    }));

    const matchedAuthors =
      authorQuery.trim() && stats
        ? stats.authors.filter((a) => a.includes(authorQuery.trim()))
        : authorQuery.trim()
          ? [authorQuery.trim()]
          : [];

    return {
      key: keyCond,
      collocations: collocRequests,
      bib: {
        authors: matchedAuthors,
        title_query: titleQuery.trim(),
        subcorpora: selectedSubcorpus ? [selectedSubcorpus] : [],
        ndc_prefix: ndcPrefix.trim(),
        published_year_min: pubYearMin.trim() ? Number(pubYearMin) : null,
        published_year_max: pubYearMax.trim() ? Number(pubYearMax) : null,
      },
      limit: pageSize,
      offset,
      context_chars: contextChars,
      columns: visibleColumns,
    };
  };

  const executeSearch = async (payload: SearchRequest) => {
    const keyEmpty = !(
      payload.key.lemma.trim() ||
      payload.key.surface.trim() ||
      payload.key.lemma_reading.trim() ||
      payload.key.pos.trim() ||
      payload.key.ctype.trim() ||
      payload.key.cform.trim() ||
      payload.key.goshu.trim()
    );
    if (keyEmpty) {
      setSearchError("キー（中心語）の検索条件を1つ以上入力または選択してください。");
      return;
    }

    setIsSearching(true);
    setSearchError(null);
    try {
      const data = await searchCorpus(payload);
      setResult(data);
      setLastPayload(payload);
    } catch (err: unknown) {
      setSearchError(
        err instanceof Error ? err.message : "検索中に予期しないエラーが発生しました"
      );
    } finally {
      setIsSearching(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const payload = buildRequestPayload(0);
    void executeSearch(payload);
  };

  const handlePageChange = (newOffset: number) => {
    if (!lastPayload) return;
    const nextPayload: SearchRequest = { ...lastPayload, offset: newOffset };
    void executeSearch(nextPayload);
  };

  const toggleColumn = (colKey: ColumnKey) => {
    setVisibleColumns((prev) =>
      prev.includes(colKey) ? prev.filter((k) => k !== colKey) : [...prev, colKey]
    );
  };

  const posOptions = stats?.pos_options ?? [
    "名詞",
    "動詞",
    "動詞-一般",
    "形容詞",
    "形状詞",
    "副詞",
    "助詞",
    "助詞-格助詞",
    "助詞-係助詞",
    "助詞-接続助詞",
    "助動詞",
  ];
  const ctypeOptions = stats?.ctype_options ?? [];
  const cformOptions = stats?.cform_options ?? [
    "未然形",
    "連用形",
    "終止形",
    "連体形",
    "仮定形",
    "命令形",
  ];
  const goshuOptions = stats?.goshu_options ?? ["和", "漢", "外", "混", "固", "記号"];

  const currentPage = result ? Math.floor(result.offset / result.limit) + 1 : 1;
  const totalPages = result
    ? Math.max(1, Math.ceil(result.total_count / result.limit))
    : 1;

  return (
    <div className="min-h-screen bg-[#f7f8fa] text-slate-900 flex flex-col">
      <AppHeader stats={stats} />

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:px-8 space-y-6">
        {statsError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
            <strong>バックエンドAPI接続エラー:</strong> {statsError}
            <div className="mt-1 text-xs text-rose-600">
              FastAPI サーバー（<code>{API_BASE_URL}</code>）が起動しているか確認してください。
            </div>
          </div>
        )}

        {/* ワンクリック検索プリセット */}
        <section className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-xs">
          <span className="text-xs font-semibold text-slate-500">検索プリセット:</span>
          <button
            type="button"
            onClick={() => applyPreset("single_hashiru")}
            className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-800 transition"
          >
            単一キー：動詞「走る」
          </button>
          <button
            type="button"
            onClick={() => applyPreset("before2_pos_hashiru")}
            className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-800 transition"
          >
            共起：2語前「助詞」＋ 動詞「走る」
          </button>
          <button
            type="button"
            onClick={() => applyPreset("verb_te")}
            className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-800 transition"
          >
            共起：動詞-一般(連用形) ＋ 直後「て」
          </button>
        </section>

        {/* ① 検索条件ビルダー */}
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* キー（中心語）条件カード */}
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-rose-600 text-xs font-bold text-white">
                  K
                </span>
                <h2 className="text-base font-bold text-slate-900">
                  キー（中心語）条件
                </h2>
                <span className="text-xs text-slate-500">
                  入力した項目はすべて AND 条件で結合されます
                </span>
              </div>
              <button
                type="button"
                onClick={() => setKeyCond(createEmptyTokenCondition())}
                className="text-xs text-slate-500 hover:text-slate-800 hover:underline"
              >
                キー条件をクリア
              </button>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <label
                  htmlFor="key-lemma"
                  className="mb-1 block text-xs font-semibold text-slate-700"
                >
                  語彙素
                </label>
                <input
                  id="key-lemma"
                  type="text"
                  value={keyCond.lemma}
                  onChange={(e) => updateKeyField("lemma", e.target.value)}
                  placeholder="例: 走る, 心, 有る"
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
                />
              </div>

              <div>
                <label
                  htmlFor="key-surface"
                  className="mb-1 block text-xs font-semibold text-slate-700"
                >
                  書字形出現形
                </label>
                <input
                  id="key-surface"
                  type="text"
                  value={keyCond.surface}
                  onChange={(e) => updateKeyField("surface", e.target.value)}
                  placeholder="例: 走っ, こころ"
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
                />
              </div>

              <div>
                <label
                  htmlFor="key-reading"
                  className="mb-1 block text-xs font-semibold text-slate-700"
                >
                  語彙素読み
                </label>
                <input
                  id="key-reading"
                  type="text"
                  value={keyCond.lemma_reading}
                  onChange={(e) => updateKeyField("lemma_reading", e.target.value)}
                  placeholder="例: ハシル, ココロ"
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
                />
              </div>

              <div>
                <label
                  htmlFor="key-match-mode"
                  className="mb-1 block text-xs font-semibold text-slate-700"
                >
                  テキスト一致方式
                </label>
                <select
                  id="key-match-mode"
                  value={keyCond.match_mode}
                  onChange={(e) =>
                    updateKeyField("match_mode", e.target.value as MatchMode)
                  }
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
                >
                  {MATCH_MODE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label
                  htmlFor="key-pos"
                  className="mb-1 block text-xs font-semibold text-slate-700"
                >
                  品詞
                </label>
                <select
                  id="key-pos"
                  value={keyCond.pos}
                  onChange={(e) => updateKeyField("pos", e.target.value)}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
                >
                  <option value="">（指定なし）</option>
                  {posOptions.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label
                  htmlFor="key-ctype"
                  className="mb-1 block text-xs font-semibold text-slate-700"
                >
                  活用型
                </label>
                <select
                  id="key-ctype"
                  value={keyCond.ctype}
                  onChange={(e) => updateKeyField("ctype", e.target.value)}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
                >
                  <option value="">（指定なし）</option>
                  {ctypeOptions.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label
                  htmlFor="key-cform"
                  className="mb-1 block text-xs font-semibold text-slate-700"
                >
                  活用形
                </label>
                <select
                  id="key-cform"
                  value={keyCond.cform}
                  onChange={(e) => updateKeyField("cform", e.target.value)}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
                >
                  <option value="">（指定なし）</option>
                  {cformOptions.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label
                  htmlFor="key-goshu"
                  className="mb-1 block text-xs font-semibold text-slate-700"
                >
                  語種
                </label>
                <select
                  id="key-goshu"
                  value={keyCond.goshu}
                  onChange={(e) => updateKeyField("goshu", e.target.value)}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
                >
                  <option value="">（指定なし）</option>
                  {goshuOptions.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </section>

          {/* 共起条件セクション（動的増減） */}
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-indigo-600 text-xs font-bold text-white">
                  C
                </span>
                <h2 className="text-base font-bold text-slate-900">
                  前方共起・後方共起条件
                </h2>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => addCollocation("before")}
                  className="inline-flex items-center gap-1 rounded-lg border border-sky-300 bg-sky-50 px-3 py-1.5 text-xs font-semibold text-sky-800 hover:bg-sky-100 transition"
                >
                  ＋ 前方共起を追加
                </button>
                <button
                  type="button"
                  onClick={() => addCollocation("after")}
                  className="inline-flex items-center gap-1 rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-800 hover:bg-emerald-100 transition"
                >
                  ＋ 後方共起を追加
                </button>
                {collocations.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setCollocations([])}
                    className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 transition"
                  >
                    すべてクリア
                  </button>
                )}
              </div>
            </div>

            {collocations.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50/70 px-4 py-4 text-center text-xs text-slate-500">
                共起条件は未指定です。上の「＋ 前方共起を追加」「＋ 後方共起を追加」ボタンから任意の数だけ条件を追加できます。
              </div>
            ) : (
              <div className="space-y-3">
                {collocations.map((col, idx) => {
                  const isBefore = col.direction === "before";
                  return (
                    <div
                      key={col.id}
                      data-testid={`collocation-block-${idx}`}
                      className={`rounded-xl border p-4 ${
                        isBefore
                          ? "border-sky-200 bg-sky-50/35"
                          : "border-emerald-200 bg-emerald-50/35"
                      }`}
                    >
                      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${
                              isBefore
                                ? "bg-sky-600 text-white"
                                : "bg-emerald-600 text-white"
                            }`}
                          >
                            {isBefore ? `◀ 前方共起 #${idx + 1}` : `▶ 後方共起 #${idx + 1}`}
                          </span>

                          <select
                            aria-label={`共起${idx + 1} 距離指定タイプ`}
                            value={col.distanceType}
                            onChange={(e) => {
                              const nextType = e.target.value as
                                | "adjacent"
                                | "exact"
                                | "within";
                              updateCollocation(col.id, (it) => ({
                                ...it,
                                distanceType: nextType,
                                distance: nextType === "adjacent" ? 1 : it.distance,
                              }));
                            }}
                            className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-800"
                          >
                            <option value="adjacent">
                              {isBefore ? "キーの直前 (1語)" : "キーの直後 (1語)"}
                            </option>
                            <option value="exact">
                              {isBefore ? "キーからちょうど N 語前" : "キーからちょうど N 語後"}
                            </option>
                            <option value="within">
                              {isBefore ? "キーから 1〜N 語前以内" : "キーから 1〜N 語後以内"}
                            </option>
                          </select>

                          {col.distanceType !== "adjacent" && (
                            <div className="inline-flex items-center gap-1.5 text-xs text-slate-700">
                              <span>N =</span>
                              <input
                                type="number"
                                aria-label={`共起${idx + 1} 距離N`}
                                min={1}
                                max={10}
                                value={col.distance}
                                onChange={(e) => {
                                  const v = Math.max(
                                    1,
                                    Math.min(10, Number(e.target.value) || 1)
                                  );
                                  updateCollocation(col.id, (it) => ({
                                    ...it,
                                    distance: v,
                                  }));
                                }}
                                className="w-16 rounded-lg border border-slate-300 bg-white px-2 py-1 text-center text-xs font-semibold"
                              />
                              <span>語</span>
                            </div>
                          )}
                        </div>

                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() =>
                              updateCollocation(col.id, (it) => ({
                                ...it,
                                showAdvanced: !it.showAdvanced,
                              }))
                            }
                            className="text-xs font-medium text-slate-600 hover:text-slate-900 hover:underline"
                          >
                            {col.showAdvanced ? "詳細を閉じる" : "詳細項目を開く"}
                          </button>
                          <button
                            type="button"
                            onClick={() => removeCollocation(col.id)}
                            className="rounded-md border border-rose-200 bg-white px-2.5 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50"
                          >
                            削除
                          </button>
                        </div>
                      </div>

                      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-700">
                            語彙素
                          </label>
                          <input
                            type="text"
                            aria-label={`共起${idx + 1} 語彙素`}
                            value={col.condition.lemma}
                            onChange={(e) =>
                              updateCollocation(col.id, (it) => ({
                                ...it,
                                condition: { ...it.condition, lemma: e.target.value },
                              }))
                            }
                            placeholder="例: て, を, の"
                            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
                          />
                        </div>

                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-700">
                            書字形出現形
                          </label>
                          <input
                            type="text"
                            aria-label={`共起${idx + 1} 書字形出現形`}
                            value={col.condition.surface}
                            onChange={(e) =>
                              updateCollocation(col.id, (it) => ({
                                ...it,
                                condition: { ...it.condition, surface: e.target.value },
                              }))
                            }
                            placeholder="表層形"
                            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
                          />
                        </div>

                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-700">
                            品詞
                          </label>
                          <select
                            aria-label={`共起${idx + 1} 品詞`}
                            value={col.condition.pos}
                            onChange={(e) =>
                              updateCollocation(col.id, (it) => ({
                                ...it,
                                condition: { ...it.condition, pos: e.target.value },
                              }))
                            }
                            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
                          >
                            <option value="">（指定なし）</option>
                            {posOptions.map((opt) => (
                              <option key={opt} value={opt}>
                                {opt}
                              </option>
                            ))}
                          </select>
                        </div>

                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-700">
                            活用形
                          </label>
                          <select
                            aria-label={`共起${idx + 1} 活用形`}
                            value={col.condition.cform}
                            onChange={(e) =>
                              updateCollocation(col.id, (it) => ({
                                ...it,
                                condition: { ...it.condition, cform: e.target.value },
                              }))
                            }
                            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
                          >
                            <option value="">（指定なし）</option>
                            {cformOptions.map((opt) => (
                              <option key={opt} value={opt}>
                                {opt}
                              </option>
                            ))}
                          </select>
                        </div>
                      </div>

                      {col.showAdvanced && (
                        <div className="mt-3 grid grid-cols-1 gap-3 border-t border-slate-200/70 pt-3 sm:grid-cols-2 lg:grid-cols-4">
                          <div>
                            <label className="mb-1 block text-xs font-medium text-slate-700">
                              語彙素読み
                            </label>
                            <input
                              type="text"
                              value={col.condition.lemma_reading}
                              onChange={(e) =>
                                updateCollocation(col.id, (it) => ({
                                  ...it,
                                  condition: {
                                    ...it.condition,
                                    lemma_reading: e.target.value,
                                  },
                                }))
                              }
                              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
                            />
                          </div>
                          <div>
                            <label className="mb-1 block text-xs font-medium text-slate-700">
                              活用型
                            </label>
                            <select
                              value={col.condition.ctype}
                              onChange={(e) =>
                                updateCollocation(col.id, (it) => ({
                                  ...it,
                                  condition: { ...it.condition, ctype: e.target.value },
                                }))
                              }
                              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
                            >
                              <option value="">（指定なし）</option>
                              {ctypeOptions.map((opt) => (
                                <option key={opt} value={opt}>
                                  {opt}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div>
                            <label className="mb-1 block text-xs font-medium text-slate-700">
                              語種
                            </label>
                            <select
                              value={col.condition.goshu}
                              onChange={(e) =>
                                updateCollocation(col.id, (it) => ({
                                  ...it,
                                  condition: { ...it.condition, goshu: e.target.value },
                                }))
                              }
                              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
                            >
                              <option value="">（指定なし）</option>
                              {goshuOptions.map((opt) => (
                                <option key={opt} value={opt}>
                                  {opt}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div>
                            <label className="mb-1 block text-xs font-medium text-slate-700">
                              一致方式
                            </label>
                            <select
                              value={col.condition.match_mode}
                              onChange={(e) =>
                                updateCollocation(col.id, (it) => ({
                                  ...it,
                                  condition: {
                                    ...it.condition,
                                    match_mode: e.target.value as MatchMode,
                                  },
                                }))
                              }
                              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
                            >
                              {MATCH_MODE_OPTIONS.map((opt) => (
                                <option key={opt.value} value={opt.value}>
                                  {opt.label}
                                </option>
                              ))}
                            </select>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          {/* 書誌フィルタ & 表示設定（折りたたみ） */}
          <section className="rounded-2xl border border-slate-200 bg-white shadow-xs">
            <button
              type="button"
              onClick={() => setShowBibFilter((v) => !v)}
              className="flex w-full items-center justify-between px-5 py-3.5 text-left text-sm font-semibold text-slate-700 hover:bg-slate-50 rounded-2xl"
            >
              <span>書誌絞り込み・表示件数設定（任意）</span>
              <span className="text-xs text-slate-400">
                {showBibFilter ? "▲ 閉じる" : "▼ 開く"}
              </span>
            </button>
            {showBibFilter && (
              <div className="grid grid-cols-1 gap-3 border-t border-slate-100 p-5 sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-700">
                    著者名（部分一致）
                  </label>
                  <input
                    type="text"
                    value={authorQuery}
                    onChange={(e) => setAuthorQuery(e.target.value)}
                    placeholder="例: 夏目漱石, 芥川"
                    className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-700">
                    作品名（部分一致）
                  </label>
                  <input
                    type="text"
                    value={titleQuery}
                    onChange={(e) => setTitleQuery(e.target.value)}
                    placeholder="例: 坊っちゃん"
                    className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-700">
                    サブコーパス（文字遣い）
                  </label>
                  <select
                    value={selectedSubcorpus}
                    onChange={(e) => setSelectedSubcorpus(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
                  >
                    <option value="">（すべて）</option>
                    {(stats?.subcorpora ?? []).map((sc) => (
                      <option key={sc} value={sc}>
                        {sc}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-700">
                    NDC 前方一致
                  </label>
                  <input
                    type="text"
                    value={ndcPrefix}
                    onChange={(e) => setNdcPrefix(e.target.value)}
                    placeholder="例: 913"
                    className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-700">
                    出版年（最小）
                  </label>
                  <input
                    type="number"
                    value={pubYearMin}
                    onChange={(e) => setPubYearMin(e.target.value)}
                    placeholder="例: 1900"
                    className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-700">
                    出版年（最大）
                  </label>
                  <input
                    type="number"
                    value={pubYearMax}
                    onChange={(e) => setPubYearMax(e.target.value)}
                    placeholder="例: 1950"
                    className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-700">
                    1ページ表示件数
                  </label>
                  <select
                    value={pageSize}
                    onChange={(e) => setPageSize(Number(e.target.value))}
                    className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
                  >
                    {[20, 50, 100, 200, 500].map((n) => (
                      <option key={n} value={n}>
                        {n} 件
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-700">
                    KWIC 前後文脈文字数
                  </label>
                  <select
                    value={contextChars}
                    onChange={(e) => setContextChars(Number(e.target.value))}
                    className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
                  >
                    {[15, 20, 30, 40, 60].map((n) => (
                      <option key={n} value={n}>
                        前後 {n} 文字
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            )}
          </section>

          {/* 検索実行ボタン */}
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={isSearching}
              className="flex-1 rounded-xl bg-indigo-700 px-6 py-3.5 text-sm font-bold text-white shadow-sm hover:bg-indigo-800 disabled:cursor-not-allowed disabled:bg-indigo-400 transition"
            >
              {isSearching ? "DuckDB で 1.52 億トークンを検索中..." : "🔍 短単位 KWIC 検索を実行"}
            </button>
          </div>
        </form>

        {/* エラー表示 */}
        {searchError && (
          <div
            role="alert"
            className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"
          >
            {searchError}
          </div>
        )}

        {/* ② 検索結果セクション */}
        {result && (
          <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-xs">
              <div className="flex flex-wrap items-center gap-3">
                <div className="rounded-lg bg-emerald-50 px-3.5 py-1.5 text-sm font-bold text-emerald-800 ring-1 ring-emerald-200">
                  総ヒット件数: {result.total_count.toLocaleString()} 件
                </div>
                <div className="rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700">
                  表示中:{" "}
                  {result.returned_count > 0
                    ? `${(result.offset + 1).toLocaleString()} 〜 ${(
                        result.offset + result.returned_count
                      ).toLocaleString()} 件`
                    : "0 件"}
                </div>
                <div className="rounded-lg bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-800">
                  実行時間: {result.elapsed_ms.toLocaleString()} ms
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <div className="inline-flex flex-wrap items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 p-1">
                  <select
                    aria-label="ダウンロード形式"
                    value={exportFormat}
                    onChange={(e) =>
                      setExportFormat(e.target.value as ExportFormat)
                    }
                    className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 focus:border-indigo-500 focus:outline-none"
                  >
                    <option value="csv">CSV (.csv)</option>
                    <option value="tsv">TSV (.tsv)</option>
                  </select>
                  <select
                    aria-label="ダウンロード文字コード"
                    value={exportEncoding}
                    onChange={(e) =>
                      setExportEncoding(e.target.value as ExportEncoding)
                    }
                    className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 focus:border-indigo-500 focus:outline-none"
                  >
                    <option value="utf8-bom">UTF-8 (BOM付き)</option>
                    <option value="sjis">Shift-JIS</option>
                  </select>
                  <button
                    type="button"
                    disabled={result.items.length === 0}
                    onClick={() =>
                      downloadKwicFile(result.items, visibleColumns, {
                        format: exportFormat,
                        encoding: exportEncoding,
                      })
                    }
                    className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-40 transition"
                  >
                    ⬇ ダウンロード
                  </button>
                </div>
                <button
                  type="button"
                  onClick={() => setShowSql((v) => !v)}
                  className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  {showSql ? "SQLを隠す" : "発行SQLを表示"}
                </button>
              </div>
            </div>

            {showSql && (
              <div className="rounded-xl border border-slate-200 bg-slate-900 p-4 text-xs text-slate-100 overflow-x-auto">
                <pre className="font-mono whitespace-pre-wrap">{result.sql}</pre>
                <div className="mt-2 border-t border-slate-700 pt-2 text-slate-400">
                  パラメータ: <code>{JSON.stringify(result.params)}</code>
                </div>
              </div>
            )}

            <KwicTable
              items={result.items}
              visibleColumns={visibleColumns}
              onToggleColumn={toggleColumn}
              onResetColumns={() => setVisibleColumns(DEFAULT_VISIBLE_COLUMNS)}
              startIndex={result.offset}
            />

            {/* ページネーション */}
            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-3 pt-2">
                <button
                  type="button"
                  disabled={isSearching || currentPage <= 1}
                  onClick={() =>
                    handlePageChange(Math.max(0, result.offset - result.limit))
                  }
                  className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"
                >
                  ← 前のページ
                </button>
                <span className="text-xs font-semibold text-slate-600 tabular-nums">
                  {currentPage.toLocaleString()} / {totalPages.toLocaleString()} ページ
                </span>
                <button
                  type="button"
                  disabled={isSearching || currentPage >= totalPages}
                  onClick={() => handlePageChange(result.offset + result.limit)}
                  className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"
                >
                  次のページ →
                </button>
              </div>
            )}
          </section>
        )}
      </main>

      <AppFooter />
    </div>
  );
}
