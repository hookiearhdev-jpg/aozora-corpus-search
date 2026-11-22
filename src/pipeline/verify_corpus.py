"""生成されたParquetコーパスの包括的セルフレビュー・検証スクリプト。

検証項目:
1. Parquetファイルのスキーマ（カラム名・順序・件数）厳密チェック
2. 著作権コンプライアンス照合（元カタログCSVと突合し「あり」混入0件を強制検証）
3. tokens.parquet の sentence_id ごとの token_index (0, 1, 2, ...) 厳密連番検証
4. start_pos / end_pos と sentences.text スライスの全件一致検証（KWIC整合性）
5. DuckDBによる中納言風共起検索SQL（token_index加減算結合）の動作・速度検証
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow.parquet as pq

EXPECTED_BOOKS_COLS = [
    "book_id",
    "title",
    "author",
    "author_birth_year",
    "published_year",
    "ndc",
    "card_url",
    "subcorpus",
]
EXPECTED_SENTENCES_COLS = ["sentence_id", "book_id", "text"]
EXPECTED_TOKENS_COLS = [
    "sentence_id",
    "token_index",
    "start_pos",
    "end_pos",
    "surface",
    "lemma",
    "lemma_reading",
    "pos",
    "ctype",
    "cform",
    "goshu",
]


def _resolve_tokens_source(processed_dir: Path) -> tuple[list[Path], str]:
    """分割 tokens_*.parquet または単一 tokens.parquet を自動検出する。"""
    shards = sorted(processed_dir.glob("tokens_*.parquet"))
    if shards:
        return shards, (processed_dir / "tokens_*.parquet").as_posix()
    single = processed_dir / "tokens.parquet"
    assert single.exists(), f"{single} または tokens_*.parquet が存在しません。"
    return [single], single.as_posix()


def verify_schemas(processed_dir: Path) -> None:
    print("=== 1. スキーマ検証 ===")
    total_bytes = 0
    for filename, expected_cols in [
        ("books.parquet", EXPECTED_BOOKS_COLS),
        ("sentences.parquet", EXPECTED_SENTENCES_COLS),
    ]:
        path = processed_dir / filename
        assert path.exists(), f"{path} が存在しません。"
        pf = pq.ParquetFile(path)
        actual_cols = pf.schema_arrow.names
        assert actual_cols == expected_cols, (
            f"{filename} のカラムが仕様と不一致:\n"
            f"  期待: {expected_cols}\n"
            f"  実際: {actual_cols}"
        )
        size_b = path.stat().st_size
        total_bytes += size_b
        print(f"  [OK] {filename}: {pf.metadata.num_rows:,} 行 ({size_b / (1024**2):.2f} MB) / カラム一致")

    token_files, _ = _resolve_tokens_source(processed_dir)
    total_token_rows = 0
    total_token_bytes = 0
    for tf in token_files:
        pf = pq.ParquetFile(tf)
        actual_cols = pf.schema_arrow.names
        assert actual_cols == EXPECTED_TOKENS_COLS, (
            f"{tf.name} のカラムが仕様と不一致:\n"
            f"  期待: {EXPECTED_TOKENS_COLS}\n"
            f"  実際: {actual_cols}"
        )
        total_token_rows += pf.metadata.num_rows
        total_token_bytes += tf.stat().st_size
    total_bytes += total_token_bytes
    label = f"tokens_*.parquet ({len(token_files)} ファイル)" if len(token_files) > 1 else "tokens.parquet"
    print(
        f"  [OK] {label}: {total_token_rows:,} 行 "
        f"({total_token_bytes / (1024**2):.2f} MB) / 全ファイルカラム一致"
    )
    print(f"  [INFO] Parquet合計サイズ: {total_bytes / (1024**2):.2f} MB ({total_bytes / (1024**3):.2f} GB)")


def verify_copyright(processed_dir: Path, catalog_csv: Path) -> None:
    print("\n=== 2. 著作権フラグ強制検証 (CRITICAL) ===")
    assert catalog_csv.exists(), f"カタログCSVが存在しません: {catalog_csv}"

    books_df = pd.read_parquet(processed_dir / "books.parquet")
    target_book_ids = set(books_df["book_id"].astype(str).str.zfill(6))
    target_book_ids_int = set(books_df["book_id"].astype(int))

    # カタログCSVの著作権列を読み込み
    cat_df = pd.read_csv(catalog_csv, dtype=str, keep_default_na=False)
    assert "作品ID" in cat_df.columns, "カタログCSVに「作品ID」列がありません。"

    # 著作権関連列を特定
    work_cr_col = "作品著作権フラグ" if "作品著作権フラグ" in cat_df.columns else "著作権フラグ"
    assert work_cr_col in cat_df.columns, f"著作権フラグ列が見つかりません: {cat_df.columns.tolist()}"

    cat_df["_book_id_int"] = cat_df["作品ID"].astype(int)
    matched = cat_df[cat_df["_book_id_int"].isin(target_book_ids_int)]

    matched_ids = set(matched["_book_id_int"])
    assert matched_ids == target_book_ids_int, (
        f"books.parquet の一部 book_id がカタログCSVと一致しません: "
        f"欠落={target_book_ids_int - matched_ids}"
    )

    # 作品著作権フラグが「なし」以外（特に「あり」）のレコードが1件でもあれば即座に失敗
    non_pd_works = matched[matched[work_cr_col].str.strip() != "なし"]
    assert len(non_pd_works) == 0, (
        f"CRITICAL VIOLATION: 著作権フラグ「なし」以外の作品が混入しています！件数={len(non_pd_works)}\n"
        f"{non_pd_works[['作品ID', '作品名', work_cr_col]].head(10)}"
    )

    # 人物著作権フラグも存在する場合は併せて検証
    person_cr_checked = False
    if "人物著作権フラグ" in matched.columns:
        person_cr_checked = True
        non_pd_persons = matched[matched["人物著作権フラグ"].str.strip() == "あり"]
        assert len(non_pd_persons) == 0, (
            f"CRITICAL VIOLATION: 人物著作権フラグ「あり」が紐づく作品が混入しています！件数={len(non_pd_persons)}\n"
            f"{non_pd_persons[['作品ID', '作品名', '姓', '名', '人物著作権フラグ']].head(10)}"
        )

    # card_url がすべて空でないことも検証（クレジット表記・出典リンク用）
    empty_urls = books_df[books_df["card_url"].isna() | (books_df["card_url"].str.strip() == "")]
    assert len(empty_urls) == 0, f"card_url が空の作品が {len(empty_urls)} 件あります。"

    print(
        f"  [OK] 全 {len(target_book_ids_int)} 作品（カタログ照合 {len(matched)} 行）において "
        f"`{work_cr_col} == 'なし'` を確認（違反: 0 件）"
    )
    if person_cr_checked:
        print("  [OK] 紐づく全人物レコードで `人物著作権フラグ == 'あり'` 混入 0 件を確認")
    print("  [OK] 全作品に図書カードURL (card_url) が設定されていることを確認")


def verify_duckdb_integrity(processed_dir: Path) -> None:
    print("\n=== 3. DuckDB 整合性・token_index 連番・KWIC 位置検証 ===")
    books_p = (processed_dir / "books.parquet").as_posix()
    sents_p = (processed_dir / "sentences.parquet").as_posix()
    _, tokens_p = _resolve_tokens_source(processed_dir)

    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = false")

    # 3-1. 参照整合性 (books <-> sentences <-> tokens)
    orphan_sents = con.execute(
        f"""
        SELECT COUNT(*)
        FROM read_parquet('{sents_p}') s
        LEFT JOIN read_parquet('{books_p}') b ON s.book_id = b.book_id
        WHERE b.book_id IS NULL
        """
    ).fetchone()[0]
    assert orphan_sents == 0, f"books.parquet に存在しない book_id を参照する文が {orphan_sents} 件あります。"

    orphan_tokens = con.execute(
        f"""
        SELECT COUNT(*)
        FROM (SELECT DISTINCT sentence_id FROM read_parquet('{tokens_p}')) t
        LEFT JOIN read_parquet('{sents_p}') s ON t.sentence_id = s.sentence_id
        WHERE s.sentence_id IS NULL
        """
    ).fetchone()[0]
    assert orphan_tokens == 0, f"sentences.parquet に存在しない sentence_id を参照するトークン文が {orphan_tokens} 件あります。"

    dup_sent_ids = con.execute(
        f"""
        SELECT COUNT(*) - COUNT(DISTINCT sentence_id)
        FROM read_parquet('{sents_p}')
        """
    ).fetchone()[0]
    assert dup_sent_ids == 0, f"sentence_id に重複が {dup_sent_ids} 件あります。"

    # 3-2. token_index の 0, 1, 2, ..., N-1 厳密連番検証 (CRITICAL)
    t_idx_start = time.perf_counter()
    invalid_token_index_sents = con.execute(
        f"""
        SELECT COUNT(*) FROM (
            SELECT
                sentence_id,
                MIN(token_index) AS min_idx,
                MAX(token_index) AS max_idx,
                COUNT(*) AS cnt,
                COUNT(DISTINCT token_index) AS distinct_cnt
            FROM read_parquet('{tokens_p}')
            GROUP BY sentence_id
            HAVING min_idx <> 0
                OR max_idx <> cnt - 1
                OR distinct_cnt <> cnt
        )
        """
    ).fetchone()[0]
    t_idx_sec = time.perf_counter() - t_idx_start
    assert invalid_token_index_sents == 0, (
        f"CRITICAL: token_index が 0..N-1 の連番になっていない文が {invalid_token_index_sents} 件あります！"
    )

    total_sents_with_tokens, total_tokens = con.execute(
        f"SELECT COUNT(DISTINCT sentence_id), COUNT(*) FROM read_parquet('{tokens_p}')"
    ).fetchone()
    total_sents = con.execute(f"SELECT COUNT(*) FROM read_parquet('{sents_p}')").fetchone()[0]
    assert total_sents == total_sents_with_tokens, (
        f"トークンが0件の文が存在します: sentences={total_sents}, with_tokens={total_sents_with_tokens}"
    )
    print(
        f"  [OK] 全 {total_sents:,} 文 / {total_tokens:,} トークンで "
        f"`token_index` が 0 から始まる重複・欠番なしの完全連番であることを確認 ({t_idx_sec:.1f}s)"
    )

    # 3-3. start_pos / end_pos と sentences.text の一致検証 (DuckDB substr は 1-indexed)
    pos_mismatch = con.execute(
        f"""
        SELECT COUNT(*)
        FROM read_parquet('{tokens_p}') t
        JOIN read_parquet('{sents_p}') s ON t.sentence_id = s.sentence_id
        WHERE substr(s.text, t.start_pos + 1, t.end_pos - t.start_pos) <> t.surface
           OR t.start_pos < 0
           OR t.end_pos <= t.start_pos
        """
    ).fetchone()[0]
    assert pos_mismatch == 0, f"start_pos/end_pos と surface の不一致が {pos_mismatch} 件あります！"

    # 3-4. 文内の start_pos 単調増加検証（各トークンの直前トークンと比較、省メモリ実行）
    token_files, _ = _resolve_tokens_source(processed_dir)
    overlap_cnt = 0
    for tf in token_files:
        tf_p = tf.as_posix()
        overlap_cnt += con.execute(
            f"""
            WITH ordered AS (
                SELECT
                    start_pos,
                    LAG(end_pos) OVER (PARTITION BY sentence_id ORDER BY token_index) AS prev_end_pos
                FROM read_parquet('{tf_p}')
            )
            SELECT COUNT(*)
            FROM ordered
            WHERE prev_end_pos IS NOT NULL AND start_pos < prev_end_pos
            """
        ).fetchone()[0]
    assert overlap_cnt == 0, f"同一文内でトークン位置が逆転・重複している箇所が {overlap_cnt} 件あります！"
    print("  [OK] 全トークンで `text[start_pos:end_pos] == surface` および単調増加を確認")

    # 3-5. 青空文庫記法のクリーニング残存チェック
    ruby_left = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{sents_p}') WHERE text LIKE '%《%' OR text LIKE '%》%'"
    ).fetchone()[0]
    note_left = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{sents_p}') WHERE text LIKE '%［＃%'"
    ).fetchone()[0]
    print(f"  [INFO] 記法残存チェック: ルビ記号残存文={ruby_left} 件 / 入力者注残存文={note_left} 件")

    # 3-6. 中納言風・共起検索SQLのパフォーマンス＆動作確認
    print("\n=== 4. DuckDB 共起検索SQL パフォーマンス検証 ===")
    # ベンチマーク1: 2語前が「品詞=助詞」＋キーが特定の動詞（語彙素='走る'）※Streamlit UIと同等のクエリ
    t_b1 = time.perf_counter()
    b1_rows = con.execute(
        f"""
        SELECT
            b.title,
            b.author,
            s.text,
            t1.start_pos,
            t1.end_pos,
            t1.surface,
            t1.lemma,
            t1.pos,
            t1.cform,
            b.card_url
        FROM read_parquet('{tokens_p}') t1
        JOIN read_parquet('{sents_p}') s ON t1.sentence_id = s.sentence_id
        JOIN read_parquet('{books_p}') b ON s.book_id = b.book_id
        JOIN read_parquet('{tokens_p}') t2
          ON t1.sentence_id = t2.sentence_id
         AND t2.token_index = t1.token_index - 2
        WHERE t1.lemma = '走る'
          AND (t1.pos = '動詞' OR t1.pos LIKE '動詞-%')
          AND (t2.pos = '助詞' OR t2.pos LIKE '助詞-%')
        ORDER BY b.book_id, s.sentence_id, t1.token_index
        LIMIT 100
        """
    ).fetchall()
    b1_select_ms = (time.perf_counter() - t_b1) * 1000

    t_b1c = time.perf_counter()
    b1_total = con.execute(
        f"""
        SELECT COUNT(*)
        FROM read_parquet('{tokens_p}') t1
        JOIN read_parquet('{tokens_p}') t2
          ON t1.sentence_id = t2.sentence_id
         AND t2.token_index = t1.token_index - 2
        WHERE t1.lemma = '走る'
          AND (t1.pos = '動詞' OR t1.pos LIKE '動詞-%')
          AND (t2.pos = '助詞' OR t2.pos LIKE '助詞-%')
        """
    ).fetchone()[0]
    b1_count_ms = (time.perf_counter() - t_b1c) * 1000
    assert b1_total > 0, "ベンチマーク1（2語前=助詞 + 動詞「走る」）のヒット数が0件です。"
    print(
        f"  [OK] 2語前(品詞='助詞') + キー(動詞・語彙素='走る'): "
        f"総ヒット {b1_total:,} 件 / SELECT(100件) {b1_select_ms:.1f} ms / COUNT {b1_count_ms:.1f} ms"
    )
    for row in b1_rows[:3]:
        title, author, text, sp, ep, surf, lemma, pos, cform, _ = row
        lctx = text[max(0, sp - 15) : sp]
        rctx = text[ep : ep + 15]
        print(f"       [{title} / {author}] ...{lctx} 【{surf}】 {rctx}... ({pos}, {cform})")

    # ベンチマーク2: 後方共起（動詞-一般・連用形 + 直後(+1)「て」）
    t0 = time.perf_counter()
    sample_rows = con.execute(
        f"""
        SELECT
            b.title,
            b.author,
            substr(s.text, GREATEST(1, t1.start_pos - 14), t1.start_pos - GREATEST(1, t1.start_pos - 14) + 1) AS left_ctx,
            t1.surface AS key_surface,
            substr(s.text, t1.end_pos + 1, 15) AS right_ctx,
            t1.lemma,
            t1.pos,
            t1.cform,
            t2.surface AS colloc_surface
        FROM read_parquet('{tokens_p}') t1
        JOIN read_parquet('{tokens_p}') t2
          ON t1.sentence_id = t2.sentence_id
         AND t2.token_index = t1.token_index + 1
        JOIN read_parquet('{sents_p}') s ON t1.sentence_id = s.sentence_id
        JOIN read_parquet('{books_p}') b ON s.book_id = b.book_id
        WHERE t1.pos = '動詞-一般'
          AND t1.cform LIKE '連用形%'
          AND t2.lemma = 'て'
          AND t2.pos LIKE '助詞%'
        LIMIT 5
        """
    ).fetchall()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    total_hits = con.execute(
        f"""
        SELECT COUNT(*)
        FROM read_parquet('{tokens_p}') t1
        JOIN read_parquet('{tokens_p}') t2
          ON t1.sentence_id = t2.sentence_id
         AND t2.token_index = t1.token_index + 1
        WHERE t1.pos = '動詞-一般'
          AND t1.cform LIKE '連用形%'
          AND t2.lemma = 'て'
          AND t2.pos LIKE '助詞%'
        """
    ).fetchone()[0]
    assert total_hits > 0, "後方共起検索サンプルクエリのヒット数が0件です。"
    print(f"  [OK] 後方共起（動詞-一般・連用形 + 直後(+1)「て」）: {total_hits:,} 件ヒット (サンプル取得 {elapsed_ms:.1f} ms)")

    con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="生成されたParquetコーパスの検証を実行します。")
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--catalog-csv", type=Path, default=Path("data/raw/list_person_all_extended_utf8.csv"))
    args = parser.parse_args()

    verify_schemas(args.processed_dir)
    verify_copyright(args.processed_dir, args.catalog_csv)
    verify_duckdb_integrity(args.processed_dir)
    print("\nALL CHECKS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n[VERIFICATION FAILED] {e}", file=sys.stderr)
        sys.exit(1)
