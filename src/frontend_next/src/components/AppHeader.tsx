"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import React from "react";
import type { CorpusStats } from "../types/corpus";

interface AppHeaderProps {
  stats: CorpusStats | null;
  subtitle?: string;
}

export function AppHeader({ stats, subtitle }: AppHeaderProps) {
  const pathname = usePathname();
  const isWorks = pathname?.startsWith("/works");

  return (
    <header className="border-b border-slate-200 bg-gradient-to-r from-slate-900 via-indigo-950 to-slate-900 text-white shadow-sm">
      <div className="mx-auto max-w-7xl px-4 pt-3 pb-5 sm:px-6 lg:px-8">
        {/* ナビゲーションバー */}
        <nav
          aria-label="メインナビゲーション"
          className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-white/10 pb-3"
        >
          <div className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-0.5 text-xs font-medium text-indigo-200 ring-1 ring-white/15">
            <span>Parquet</span>
            <span>•</span>
            <span>UniDic 短単位検索</span>
          </div>

          <div className="flex items-center gap-2">
            <Link
              href="/"
              className={`inline-flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs font-semibold transition ${
                !isWorks
                  ? "bg-white text-slate-900 shadow-xs"
                  : "bg-white/10 text-slate-200 hover:bg-white/20 hover:text-white"
              }`}
            >
              🔍 コーパス検索
            </Link>
            <Link
              href="/works"
              className={`inline-flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs font-semibold transition ${
                isWorks
                  ? "bg-white text-slate-900 shadow-xs"
                  : "bg-white/10 text-slate-200 hover:bg-white/20 hover:text-white"
              }`}
            >
              📚 収録作品一覧
            </Link>
          </div>
        </nav>

        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
              {isWorks ? "青空文庫 収録作品一覧" : "青空文庫 短単位コーパス検索"}
            </h1>
            {subtitle && (
              <p className="mt-1 text-sm text-slate-300">{subtitle}</p>
            )}
          </div>

          {/* コーパス統計メトリクス */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div className="rounded-lg bg-white/10 px-3 py-2 ring-1 ring-white/10">
              <div className="text-[11px] text-slate-300">収録作品数</div>
              <div className="text-base font-bold tabular-nums">
                {stats ? `${stats.book_count.toLocaleString()}` : "..."}
              </div>
            </div>
            <div className="rounded-lg bg-white/10 px-3 py-2 ring-1 ring-white/10">
              <div className="text-[11px] text-slate-300">著者数</div>
              <div className="text-base font-bold tabular-nums">
                {stats ? `${stats.author_count.toLocaleString()}` : "..."}
              </div>
            </div>
            <div className="rounded-lg bg-white/10 px-3 py-2 ring-1 ring-white/10">
              <div className="text-[11px] text-slate-300">総文数</div>
              <div className="text-base font-bold tabular-nums">
                {stats ? `${stats.sentence_count.toLocaleString()}` : "..."}
              </div>
            </div>
            <div className="rounded-lg bg-white/10 px-3 py-2 ring-1 ring-white/10">
              <div className="text-[11px] text-slate-300">総短単位数</div>
              <div className="text-base font-bold tabular-nums text-amber-300">
                {stats ? `${stats.token_count.toLocaleString()}` : "..."}
              </div>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
