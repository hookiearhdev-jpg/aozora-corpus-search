# 青空文庫「中納言風」短単位コーパス検索 Webアプリ

青空文庫のパブリックドメイン（著作権保護期間満了・著作権フラグ「なし」）作品を対象に、国立国語研究所「中納言」の短単位検索に準拠した言語学的検索（キー＋前方/後方共起・語彙素・品詞・活用形・語種・KWIC表示・CSVダウンロード）を実行できるプロトタイプアプリケーションです。

## 構成

- **データパイプライン**:
  - スモールスタート（100作品）: [src/pipeline/build_corpus.py](src/pipeline/build_corpus.py)
  - フルスケール（全約1.7万作品・マルチプロセス並列＆分割Parquet）: [src/pipeline/build_corpus_full.py](src/pipeline/build_corpus_full.py)
  - テキストクリーニング: [src/pipeline/text_cleaner.py](src/pipeline/text_cleaner.py)
  - 青空文庫カタログCSVから「作品著作権フラグ = `なし`」（かつ人物著作権フラグ「あり」を含まない）作品のみを `assert` で強制検証して抽出
  - ルビ・入力者注・ヘッダ/フッタ除去、文分割、`fugashi` + `unidic-lite` による UniDic 形態素解析
  - `data/processed/` に `books.parquet`, `sentences.parquet`, `tokens_*.parquet` を `zstd` 圧縮で出力
- **検索バックエンド**: [src/backend/search_engine.py](src/backend/search_engine.py)
  - Parquet + DuckDB による動的SQL生成（パラメータ化クエリ、単一 `tokens.parquet` / 分割 `tokens_*.parquet` 両対応、1.5億トークン向けハッシュ結合＆1クエリ最適化）
  - 同一 `sentence_id` 内での `token_index` 加減算による高速自己結合（前方/後方共起・直前/直後・N語・1〜N語以内）
- **API サーバー (FastAPI)**: [src/api/main.py](src/api/main.py)
  - `GET /api/health`, `GET /api/stats`, `POST /api/search`（CORS対応）
- **Web フロントエンド (Next.js App Router + Tailwind CSS)**: [src/frontend_next/](src/frontend_next/)
  - 検索条件ビルダー、前方/後方共起ブロックの動的増減、中納言風 KWIC テーブル（前文脈右揃え｜キー朱赤中央揃え｜後文脈左揃え）、表示列トグル、クライアントサイド UTF-8 BOM 付 CSV ダウンロード、青空文庫（CC BY 4.0）クレジット表記＆図書カードリンク
- **プロトタイプ UI (Streamlit)**: [src/frontend/app.py](src/frontend/app.py)

## セットアップ & 実行手順

```bash
# 1. 仮想環境の作成と依存パッケージのインストール
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 2-A. コーパス構築（100作品スモールスタート）
python src/pipeline/build_corpus.py --limit 100

# 2-B. フルスケールコーパス構築（著作権フリー全約1.7万作品・並列処理）
python src/pipeline/build_corpus_full.py

# 3. コーパス整合性・著作権コンプライアンス・パフォーマンス検証
python src/pipeline/verify_corpus.py

# 4-A. 本番構成（FastAPI + Next.js）を同時起動
# Windows:
run_app.bat
# macOS / Linux / Git Bash:
./run_app.sh

# 4-B. Streamlit プロトタイプ起動
streamlit run src/frontend/app.py
```

## ライセンス・出典

- 本文・書誌情報は [青空文庫](https://www.aozora.gr.jp/) の公開データ（著作権フラグ「なし」の作品のみ）からローカル生成した Parquet コーパスを使用しています。
- 青空文庫の書誌情報は [CC BY 4.0（クリエイティブ・コモンズ 表示 4.0 国際）](https://creativecommons.org/licenses/by/4.0/deed.ja) に基づき利用しています。
