import React from "react";

export function AppFooter() {
  return (
    <footer className="mt-12 border-t border-slate-200 bg-white">
      <div className="mx-auto max-w-7xl px-4 py-6 text-xs leading-relaxed text-slate-600 sm:px-6 lg:px-8 space-y-1.5">
        <p className="font-semibold text-slate-800">出典・ライセンス表記</p>
        <p>
          本アプリケーションの本文データは、
          <a
            href="https://www.aozora.gr.jp/"
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-indigo-700 hover:text-indigo-900 hover:underline"
          >
            青空文庫
          </a>
          の公開データ（著作権保護期間満了・著作権フラグ「なし」の作品のみ）に対し、検索・言語解析用の前処理（ルビ・注記の除去、形態素解析等）を行って構築した独自コーパスより配信しています。
        </p>
        <p>
          また、青空文庫の書誌情報（作品名・著者名・図書カードURL等）は、
          <a
            href="https://creativecommons.org/licenses/by/4.0/deed.ja"
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-indigo-700 hover:text-indigo-900 hover:underline"
          >
            クリエイティブ・コモンズ 表示 4.0 国際（CC BY 4.0）
          </a>{" "}
          ライセンスに基づき、一部加工（検索用フォーマットへの変換等）の上で利用しています。各用例の底本情報・入力者および校正者クレジット等の詳細は、検索結果内の「作品名」または「図書カードURL」リンク先の青空文庫公式ページよりご確認いただけます。
        </p>
        <p className="text-slate-500">
          ※本サービスは個人による開発・運営であり、青空文庫の公式サービスや関与・公認を受けたものではありません。
        </p>
      </div>
    </footer>
  );
}
