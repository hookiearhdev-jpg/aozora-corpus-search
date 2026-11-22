# 青空文庫「中納言風」コーパス検索Webアプリ：プロジェクト絶対ルール

## 1. 著作権・コンプライアンス遵守 (CRITICAL)
- **著作権フィルタの徹底**: 青空文庫カタログCSV（`list_person_all_extended_utf8.csv`）の「著作権フラグ」列が **`なし`** の作品のみを処理対象とすること。「あり」の作品の混入は法的インシデントになるため絶対に禁止。抽出処理時に必ず `assert` 等を用いて強制検証すること。
- **データアクセス制約**: 青空文庫サーバーへの直リンクや都度スクレイピングは禁止。必ず自前生成したParquetファイルからデータを配信すること。
- **クレジット表記**: 画面フッターに青空文庫の書誌情報ライセンス（CC BY 4.0）に基づく出典表記と、検索結果から元の「図書カードURL」へのリンクを設けること。

## 2. アーキテクチャと技術スタック
- **高速化の維持**: 1.7万作品規模へのスケールを見据え、RDBではなく **Parquet（列指向） + DuckDB** の構成を厳守すること。
- **形態素解析**: UniDic準拠のタグ体系（`fugashi` + `unidic-lite` 等）を使用すること。

## 3. データベース設計方針 (Parquet Schema 厳守)
以下のテーブル構造とカラム名をプロジェクト全体で厳守すること。
1. `books.parquet`: `book_id`, `title`, `author`, `author_birth_year`, `published_year`, `ndc`, `card_url`, `subcorpus`
2. `sentences.parquet`: `sentence_id` (文ID), `book_id`, `text` (1文単位のクリーンな本文)
3. `tokens.parquet`: 
   - 必須インデックス: `sentence_id` (文ID), **`token_index` (文頭からの単語連番0,1,2... ※共起距離計算用 CRITICAL)**
   - 形態素情報: `start_pos`, `end_pos`, `surface`, `lemma`, `lemma_reading`, `pos`, `ctype`, `cform`, `goshu`

## 4. 開発・検証プロセス
- まずは著作権フラグ「なし」の**100作品**でスモールスタートすること。
- 実装後は必ずエージェント自身のセルフレビューにて「著作権フラグの除外漏れ」「共起検索のためのSQLロジックや `token_index` にズレがないか」をダブルチェックすること。