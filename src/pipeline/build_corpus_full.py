"""青空文庫「著作権フラグ：なし」全作品（約1.7万作品）フルスケールParquet構築パイプライン。

設計上の重要ポイント:
1. 著作権コンプライアンス厳守 (CRITICAL):
   - カタログCSVの「作品著作権フラグ == 'なし'」（かつ紐づく全人物で「人物著作権フラグ != 'あり'」）
     の作品のみを対象とし、抽出時・ダウンロード前・ビルド前に必ず assert で強制検証する。
   - 著作権違反の AssertionError は絶対に握りつぶさず即停止する。
2. 高速化・省メモリ（OOM防止）:
   - ダウンロード: ThreadPoolExecutor + スレッドローカル requests.Session（Keep-Alive + リトライ）
   - 形態素解析: ProcessPoolExecutor によるマルチコア並列処理（各ワーカープロセス内で fugashi.Tagger を1回だけ初期化）
   - 分割Parquet出力: 一定作品数ごと（デフォルト500作品ごと）に `tokens_0001.parquet`, `tokens_0002.parquet` ... へ
     シャード書き出しし、Row Group 単位で逐次フラッシュしてメモリ使用量を一定以下に保つ。
3. フォールトトレランス:
   - 個別作品のダウンロード失敗・壊れたZIP・デコード異常・解析例外が発生しても全体を止めず、
     `error_log.txt` に作品IDとエラー内容を記録してスキップする。

使い方:
  1. 一括実行:
     python src/pipeline/build_corpus_full.py
  2. ダウンロードとオフライン並列ビルドを分離実行:
     python src/pipeline/build_corpus_full.py --mode fetch
     python src/pipeline/build_corpus_full.py --mode build
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import threading
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fugashi
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from tqdm import tqdm

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.pipeline.build_corpus import (
    BOOKS_SCHEMA,
    CATALOG_CSV_NAME,
    SENTENCES_SCHEMA,
    TOKENS_SCHEMA,
    USER_AGENT,
    _clean_feature,
    _format_author,
    _normalize_ndc,
    _parse_year,
    _read_txt_from_zip,
    ensure_catalog_csv,
    load_and_filter_catalog,
)
from src.pipeline.text_cleaner import extract_clean_sentences

# ワーカープロセス単位で保持する fugashi.Tagger（初期化コストを1回に抑える）
_WORKER_TAGGER: Optional[fugashi.Tagger] = None
# ダウンロードスレッドローカル Session
_THREAD_LOCAL = threading.local()

AOZORA_CARDS_PREFIX = "https://www.aozora.gr.jp/cards/"
GITHUB_MIRROR_CARDS_PREFIX = (
    "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/"
)


def _get_thread_session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        adapter = requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=16)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _THREAD_LOCAL.session = session
    return session


def _init_worker_tagger() -> None:
    global _WORKER_TAGGER
    _WORKER_TAGGER = fugashi.Tagger()


def _download_single_zip(
    rec: Dict[str, Any],
    zips_dir: Path,
    timeout: int = 25,
    max_retries: int = 3,
) -> Tuple[int, str, bool, Optional[str]]:
    """1作品分のZIPをダウンロードして検証・キャッシュする（スレッドワーカー用）。

    Returns:
        (book_id, title, success, error_message)
    """
    # CRITICAL: ダウンロード直前の著作権フラグ強制検証
    assert rec["copyright_flag"] == "なし", (
        f"CRITICAL: 著作権フラグ違反を検知: book_id={rec['book_id']}"
    )

    book_id = int(rec["book_id"])
    title = str(rec["title"])
    url = str(rec["text_url"])
    zip_path = zips_dir / f"{book_id:06d}.zip"

    # 既存キャッシュの健全性確認
    if zip_path.exists() and zip_path.stat().st_size > 0:
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                if any(n.lower().endswith(".txt") for n in zf.namelist()):
                    return book_id, title, True, None
        except zipfile.BadZipFile:
            zip_path.unlink(missing_ok=True)

    session = _get_thread_session()
    candidate_urls = [url]
    if url.startswith(AOZORA_CARDS_PREFIX):
        candidate_urls.append(url.replace(AOZORA_CARDS_PREFIX, GITHUB_MIRROR_CARDS_PREFIX, 1))

    last_err = ""
    for attempt in range(max_retries):
        target_url = candidate_urls[0] if attempt < max_retries - 1 else candidate_urls[-1]
        try:
            resp = session.get(target_url, timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504):
                last_err = f"HTTP {resp.status_code} ({target_url})"
                time.sleep(0.5 * (2**attempt))
                continue
            resp.raise_for_status()

            content = resp.content
            with zipfile.ZipFile(io.BytesIO(content), "r") as zf:
                txt_names = [n for n in zf.namelist() if n.lower().endswith(".txt")]
                if not txt_names:
                    return book_id, title, False, f"ZIP内に.txtが存在しません ({target_url})"

            # 原子的書き込み（途中破損ファイルが残らないように一時ファイル経由で置換）
            tmp_path = zips_dir / f"{book_id:06d}.zip.tmp"
            tmp_path.write_bytes(content)
            os.replace(tmp_path, zip_path)
            return book_id, title, True, None
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc} ({target_url})"
            time.sleep(0.3 * (attempt + 1))

    return book_id, title, False, last_err


def _process_single_book_worker(
    rec: Dict[str, Any],
) -> Tuple[int, Optional[Dict[str, Any]], Optional[List[str]], Optional[List[Tuple[int, List[int], List[int], List[int], List[str], List[str], List[str], List[str], List[str], List[str], List[str]]]], Optional[str]]:
    """1作品分のテキスト抽出・文分割・形態素解析を実行する（プロセスワーカー用）。

    メモリ・IPC通信コスト削減のため、辞書リストではなく列リスト（タプル）で返す。
    Returns:
        (book_id, book_meta, sentences_list, per_sent_token_columns, error_message)
    """
    # CRITICAL: ワーカー側でも著作権フラグを強制検証
    assert rec["copyright_flag"] == "なし", (
        f"CRITICAL: ワーカーで著作権フラグ違反を検知: book_id={rec['book_id']}"
    )

    book_id = int(rec["book_id"])
    zip_path = Path(str(rec["zip_path"]))
    tagger = _WORKER_TAGGER
    if tagger is None:
        tagger = fugashi.Tagger()

    try:
        if not zip_path.exists():
            return book_id, None, None, None, f"ZIPファイルが存在しません: {zip_path}"

        raw_bytes = _read_txt_from_zip(zip_path)
        sentences = extract_clean_sentences(raw_bytes)
        if not sentences:
            return book_id, None, None, None, "クリーニング後の有効文が0件です"

        valid_sentences: List[str] = []
        per_sent_tokens: List[
            Tuple[
                int,
                List[int],
                List[int],
                List[int],
                List[str],
                List[str],
                List[str],
                List[str],
                List[str],
                List[str],
                List[str],
            ]
        ] = []

        for sent_text in sentences:
            cursor = 0
            token_index = 0
            t_idx: List[int] = []
            s_pos: List[int] = []
            e_pos: List[int] = []
            surf: List[str] = []
            lemm: List[str] = []
            lread: List[str] = []
            pos_l: List[str] = []
            ct_l: List[str] = []
            cf_l: List[str] = []
            go_l: List[str] = []

            for word in tagger(sent_text):
                surface = word.surface
                if not surface:
                    continue

                start_pos = sent_text.find(surface, cursor)
                if start_pos == -1:
                    raise ValueError(
                        f"トークン位置特定失敗: surface={surface!r}, cursor={cursor}, text={sent_text[:80]!r}"
                    )
                end_pos = start_pos + len(surface)
                cursor = end_pos

                f = word.feature
                p1, p2, p3, p4 = f.pos1, f.pos2, f.pos3, f.pos4
                if p4 and p4 != "*":
                    pos = f"{p1}-{p2}-{p3}-{p4}"
                elif p3 and p3 != "*":
                    pos = f"{p1}-{p2}-{p3}"
                elif p2 and p2 != "*":
                    pos = f"{p1}-{p2}"
                elif p1 and p1 != "*":
                    pos = p1
                else:
                    pos = "不明"

                t_idx.append(token_index)
                s_pos.append(start_pos)
                e_pos.append(end_pos)
                surf.append(surface)
                lemm.append(_clean_feature(f.lemma) or surface)
                lread.append(_clean_feature(f.lForm))
                pos_l.append(pos)
                ct_l.append(_clean_feature(f.cType))
                cf_l.append(_clean_feature(f.cForm))
                go_l.append(_clean_feature(f.goshu))
                token_index += 1

            if token_index == 0:
                continue

            valid_sentences.append(sent_text)
            per_sent_tokens.append(
                (token_index, t_idx, s_pos, e_pos, surf, lemm, lread, pos_l, ct_l, cf_l, go_l)
            )

        if not valid_sentences:
            return book_id, None, None, None, "形態素解析後の有効文が0件です"

        book_meta = {
            "book_id": book_id,
            "title": str(rec["title"]),
            "author": str(rec["author"]),
            "author_birth_year": rec["author_birth_year"],
            "published_year": rec["published_year"],
            "ndc": str(rec["ndc"]),
            "card_url": str(rec["card_url"]),
            "subcorpus": str(rec["subcorpus"]),
        }
        return book_id, book_meta, valid_sentences, per_sent_tokens, None

    except AssertionError:
        # 著作権関連の AssertionError は絶対に握りつぶさない
        raise
    except Exception as exc:
        return book_id, None, None, None, f"{type(exc).__name__}: {exc}"


def build_full_manifest_records(
    raw_df: pd.DataFrame,
    safe_books_df: pd.DataFrame,
    zips_dir: Path,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """著作権フリー全作品（件数制限なし、テスト時のみ --limit 指定可）のレコード一覧を構築する。"""
    target_df = safe_books_df.sort_values("book_id_int", ascending=True).copy()
    if limit is not None and limit > 0:
        target_df = target_df.head(limit).copy()

    # CRITICAL ASSERTION: 最終対象全件を元カタログCSVと突合して著作権フラグ「なし」を強制検証
    target_work_ids = set(target_df["作品ID"])
    matched_raw = raw_df[raw_df["作品ID"].isin(target_work_ids)]
    assert len(matched_raw) > 0, "対象作品が0件です。"
    assert (matched_raw["作品著作権フラグ"].str.strip() == "なし").all(), (
        "CRITICAL: フルビルド対象に作品著作権フラグ「なし」以外が含まれています！"
    )
    assert not (matched_raw["作品著作権フラグ"].str.strip() == "あり").any(), (
        "CRITICAL: フルビルド対象に作品著作権フラグ「あり」が混入しています！"
    )
    assert not (matched_raw["人物著作権フラグ"].str.strip() == "あり").any(), (
        "CRITICAL: フルビルド対象に人物著作権フラグ「あり」が混入しています！"
    )

    records: List[Dict[str, Any]] = []
    for row in target_df.itertuples(index=False):
        book_id_int = int(row.book_id_int)
        records.append(
            {
                "book_id": book_id_int,
                "work_id_str": str(row.作品ID),
                "title": str(row.作品名).strip(),
                "author": str(row.author_full),
                "author_birth_year": _parse_year(str(row.生年月日)),
                "published_year": _parse_year(
                    str(row.初出),
                    str(row.底本の親本初版発行年1),
                    str(row.底本初版発行年1),
                ),
                "ndc": _normalize_ndc(str(row.分類番号)),
                "card_url": str(row.図書カードURL).strip(),
                "subcorpus": str(row.文字遣い種別).strip() or "その他",
                "copyright_flag": str(row.作品著作権フラグ).strip(),
                "text_url": str(row.テキストファイルURL).strip(),
                "zip_path": str((zips_dir / f"{book_id_int:06d}.zip").as_posix()),
            }
        )

    assert all(r["copyright_flag"] == "なし" for r in records), (
        "CRITICAL: マニフェスト内に著作権フラグ「なし」以外が混入しています！"
    )
    return records


def run_fetch_phase(
    records: List[Dict[str, Any]],
    raw_dir: Path,
    error_log_path: Path,
    download_workers: int = 8,
) -> Path:
    """全作品のテキストZIPをマルチスレッドでダウンロードし、成功分マニフェストを保存する。"""
    zips_dir = raw_dir / "zips"
    zips_dir.mkdir(parents=True, exist_ok=True)
    error_log_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = raw_dir / "selected_books_full.json"

    rec_by_id = {int(r["book_id"]): r for r in records}
    succeeded_ids: List[int] = []
    errors: List[str] = []

    print(
        f"[INFO] ダウンロード開始: 対象 {len(records):,} 作品 (並列スレッド={download_workers})"
    )
    t0 = time.perf_counter()

    with ThreadPoolExecutor(max_workers=download_workers) as executor:
        futures = {
            executor.submit(_download_single_zip, rec, zips_dir): int(rec["book_id"])
            for rec in records
        }
        for fut in tqdm(as_completed(futures), total=len(futures), desc="全作品ZIP取得", unit="作品"):
            book_id, title, ok, err = fut.result()
            if ok:
                succeeded_ids.append(book_id)
            else:
                errors.append(f"[FETCH_ERROR] book_id={book_id:06d} title={title} reason={err}")

    succeeded_ids.sort()
    succeeded_records = [rec_by_id[bid] for bid in succeeded_ids]

    # CRITICAL ASSERTION
    assert all(r["copyright_flag"] == "なし" for r in succeeded_records), (
        "CRITICAL: 取得済みレコードに著作権フラグ「なし」以外が混入しています！"
    )

    manifest_path.write_text(
        json.dumps(succeeded_records, ensure_ascii=False),
        encoding="utf-8",
    )

    if errors:
        with error_log_path.open("a", encoding="utf-8") as f:
            f.write(
                f"\n--- Fetch Phase ({datetime.now().isoformat(timespec='seconds')}) "
                f"errors={len(errors)} ---\n"
            )
            for line in sorted(errors):
                f.write(line + "\n")

    elapsed = time.perf_counter() - t0
    print(
        f"[INFO] ダウンロード完了 ({elapsed:.1f}s): 成功 {len(succeeded_records):,} 作品 / "
        f"失敗(スキップ) {len(errors):,} 作品 -> {manifest_path}"
    )
    return manifest_path


def _flush_token_buffers(
    writer: pq.ParquetWriter,
    buf_sid: List[int],
    buf_tidx: List[int],
    buf_spos: List[int],
    buf_epos: List[int],
    buf_surf: List[str],
    buf_lemm: List[str],
    buf_lread: List[str],
    buf_pos: List[str],
    buf_ct: List[str],
    buf_cf: List[str],
    buf_go: List[str],
) -> None:
    if not buf_sid:
        return
    table = pa.table(
        {
            "sentence_id": pa.array(buf_sid, type=pa.int64()),
            "token_index": pa.array(buf_tidx, type=pa.int32()),
            "start_pos": pa.array(buf_spos, type=pa.int32()),
            "end_pos": pa.array(buf_epos, type=pa.int32()),
            "surface": pa.array(buf_surf, type=pa.string()),
            "lemma": pa.array(buf_lemm, type=pa.string()),
            "lemma_reading": pa.array(buf_lread, type=pa.string()),
            "pos": pa.array(buf_pos, type=pa.string()),
            "ctype": pa.array(buf_ct, type=pa.string()),
            "cform": pa.array(buf_cf, type=pa.string()),
            "goshu": pa.array(buf_go, type=pa.string()),
        },
        schema=TOKENS_SCHEMA,
    )
    writer.write_table(table)
    buf_sid.clear()
    buf_tidx.clear()
    buf_spos.clear()
    buf_epos.clear()
    buf_surf.clear()
    buf_lemm.clear()
    buf_lread.clear()
    buf_pos.clear()
    buf_ct.clear()
    buf_cf.clear()
    buf_go.clear()


def _flush_sentence_buffers(
    writer: pq.ParquetWriter,
    buf_sid: List[int],
    buf_bid: List[int],
    buf_text: List[str],
) -> None:
    if not buf_sid:
        return
    table = pa.table(
        {
            "sentence_id": pa.array(buf_sid, type=pa.int64()),
            "book_id": pa.array(buf_bid, type=pa.int64()),
            "text": pa.array(buf_text, type=pa.string()),
        },
        schema=SENTENCES_SCHEMA,
    )
    writer.write_table(table)
    buf_sid.clear()
    buf_bid.clear()
    buf_text.clear()


def run_build_phase(
    manifest_path: Path,
    catalog_csv: Path,
    processed_dir: Path,
    error_log_path: Path,
    workers: int,
    books_per_shard: int = 500,
    batch_size: int = 64,
    token_row_group_size: int = 250_000,
) -> None:
    """全作品をマルチプロセス並列で形態素解析し、分割Parquet（tokens_XXXX.parquet）へ出力する。"""
    assert manifest_path.exists(), f"マニフェストが存在しません: {manifest_path}"
    assert catalog_csv.exists(), f"カタログCSVが存在しません: {catalog_csv}"

    manifest_records: List[Dict[str, Any]] = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )

    # CRITICAL ASSERTION: ビルド直前に元カタログCSV全行と突合して著作権フラグ「なし」を再検証
    raw_df = pd.read_csv(catalog_csv, dtype=str, keep_default_na=False)
    manifest_work_ids = {str(r["work_id_str"]) for r in manifest_records}
    matched_raw = raw_df[raw_df["作品ID"].isin(manifest_work_ids)]
    assert len(matched_raw) > 0, "元カタログCSVとの照合結果が空です。"
    assert (matched_raw["作品著作権フラグ"].str.strip() == "なし").all(), (
        "CRITICAL: ビルド対象に作品著作権フラグ「なし」以外が含まれています！"
    )
    assert not (matched_raw["作品著作権フラグ"].str.strip() == "あり").any(), (
        "CRITICAL: ビルド対象に作品著作権フラグ「あり」が混入しています！"
    )
    assert not (matched_raw["人物著作権フラグ"].str.strip() == "あり").any(), (
        "CRITICAL: ビルド対象に人物著作権フラグ「あり」が混入しています！"
    )
    print(
        f"[OK] ビルド前コンプライアンス検証通過: 全 {len(manifest_records):,} 作品の著作権フラグ「なし」を確認"
    )

    processed_dir.mkdir(parents=True, exist_ok=True)
    error_log_path.parent.mkdir(parents=True, exist_ok=True)

    # 古いParquetファイル（旧単一 tokens.parquet や前回シャード）をクリーンアップして二重読込を防止
    for old_file in list(processed_dir.glob("tokens*.parquet")) + [
        processed_dir / "sentences.parquet",
        processed_dir / "books.parquet",
    ]:
        if old_file.exists():
            old_file.unlink()

    sentences_out = processed_dir / "sentences.parquet"
    books_out = processed_dir / "books.parquet"

    sent_writer = pq.ParquetWriter(sentences_out, SENTENCES_SCHEMA, compression="zstd")
    shard_idx = 1
    books_in_current_shard = 0
    token_writer = pq.ParquetWriter(
        processed_dir / f"tokens_{shard_idx:04d}.parquet",
        TOKENS_SCHEMA,
        compression="zstd",
    )

    books_rows: List[Dict[str, Any]] = []
    build_errors: List[str] = []

    sentence_id_seq = 1
    total_sentences = 0
    total_tokens = 0

    # 文・トークンの列指向バッファ（Row Group単位で逐次フラッシュしOOMを完全防止）
    s_buf_sid: List[int] = []
    s_buf_bid: List[int] = []
    s_buf_text: List[str] = []

    t_buf_sid: List[int] = []
    t_buf_tidx: List[int] = []
    t_buf_spos: List[int] = []
    t_buf_epos: List[int] = []
    t_buf_surf: List[str] = []
    t_buf_lemm: List[str] = []
    t_buf_lread: List[str] = []
    t_buf_pos: List[str] = []
    t_buf_ct: List[str] = []
    t_buf_cf: List[str] = []
    t_buf_go: List[str] = []

    SENT_FLUSH_SIZE = 20_000
    t0 = time.perf_counter()

    print(
        f"[INFO] 並列形態素解析＆分割Parquet生成開始: "
        f"workers={workers}, batch_size={batch_size}, books_per_shard={books_per_shard}"
    )

    try:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_worker_tagger,
        ) as executor:
            pbar = tqdm(total=len(manifest_records), desc="並列形態素解析 & Parquet生成", unit="作品")

            for batch_start in range(0, len(manifest_records), batch_size):
                batch = manifest_records[batch_start : batch_start + batch_size]
                # executor.map は入力順序（book_id昇順）を保持して結果を返すため、
                # sentence_id が全コーパス・全シャードで完全に単調増加する
                for res in executor.map(_process_single_book_worker, batch):
                    book_id, book_meta, valid_sents, per_sent_tokens, err = res
                    pbar.update(1)

                    if err is not None or book_meta is None or valid_sents is None or per_sent_tokens is None:
                        build_errors.append(f"[BUILD_ERROR] book_id={book_id:06d} reason={err}")
                        continue

                    # シャード切り替え（books_per_shard 作品ごとに分割ファイルをロールオーバー）
                    if books_in_current_shard >= books_per_shard:
                        _flush_token_buffers(
                            token_writer,
                            t_buf_sid,
                            t_buf_tidx,
                            t_buf_spos,
                            t_buf_epos,
                            t_buf_surf,
                            t_buf_lemm,
                            t_buf_lread,
                            t_buf_pos,
                            t_buf_ct,
                            t_buf_cf,
                            t_buf_go,
                        )
                        token_writer.close()
                        shard_idx += 1
                        books_in_current_shard = 0
                        token_writer = pq.ParquetWriter(
                            processed_dir / f"tokens_{shard_idx:04d}.parquet",
                            TOKENS_SCHEMA,
                            compression="zstd",
                        )

                    books_rows.append(book_meta)
                    books_in_current_shard += 1

                    for sent_text, tok_tuple in zip(valid_sents, per_sent_tokens):
                        (
                            tok_count,
                            t_idx,
                            s_pos,
                            e_pos,
                            surf,
                            lemm,
                            lread,
                            pos_l,
                            ct_l,
                            cf_l,
                            go_l,
                        ) = tok_tuple

                        # インラインで token_index の 0..N-1 連番を保証
                        assert t_idx[0] == 0 and t_idx[-1] == tok_count - 1

                        sid = sentence_id_seq
                        s_buf_sid.append(sid)
                        s_buf_bid.append(book_id)
                        s_buf_text.append(sent_text)

                        t_buf_sid.extend([sid] * tok_count)
                        t_buf_tidx.extend(t_idx)
                        t_buf_spos.extend(s_pos)
                        t_buf_epos.extend(e_pos)
                        t_buf_surf.extend(surf)
                        t_buf_lemm.extend(lemm)
                        t_buf_lread.extend(lread)
                        t_buf_pos.extend(pos_l)
                        t_buf_ct.extend(ct_l)
                        t_buf_cf.extend(cf_l)
                        t_buf_go.extend(go_l)

                        sentence_id_seq += 1
                        total_sentences += 1
                        total_tokens += tok_count

                        if len(s_buf_sid) >= SENT_FLUSH_SIZE:
                            _flush_sentence_buffers(sent_writer, s_buf_sid, s_buf_bid, s_buf_text)

                        if len(t_buf_sid) >= token_row_group_size:
                            _flush_token_buffers(
                                token_writer,
                                t_buf_sid,
                                t_buf_tidx,
                                t_buf_spos,
                                t_buf_epos,
                                t_buf_surf,
                                t_buf_lemm,
                                t_buf_lread,
                                t_buf_pos,
                                t_buf_ct,
                                t_buf_cf,
                                t_buf_go,
                            )

            pbar.close()

        # 残バッファのフラッシュ
        _flush_sentence_buffers(sent_writer, s_buf_sid, s_buf_bid, s_buf_text)
        _flush_token_buffers(
            token_writer,
            t_buf_sid,
            t_buf_tidx,
            t_buf_spos,
            t_buf_epos,
            t_buf_surf,
            t_buf_lemm,
            t_buf_lread,
            t_buf_pos,
            t_buf_ct,
            t_buf_cf,
            t_buf_go,
        )
    finally:
        sent_writer.close()
        token_writer.close()

    # books.parquet を出力（正常に処理された作品のみ）
    books_table = pa.Table.from_pylist(books_rows, schema=BOOKS_SCHEMA)
    pq.write_table(books_table, books_out, compression="zstd")

    if build_errors:
        with error_log_path.open("a", encoding="utf-8") as f:
            f.write(
                f"\n--- Build Phase ({datetime.now().isoformat(timespec='seconds')}) "
                f"errors={len(build_errors)} ---\n"
            )
            for line in build_errors:
                f.write(line + "\n")

    elapsed = time.perf_counter() - t0
    token_files = sorted(processed_dir.glob("tokens_*.parquet"))
    total_bytes = (
        books_out.stat().st_size
        + sentences_out.stat().st_size
        + sum(p.stat().st_size for p in token_files)
    )
    print("\n=== フルスケール Parquet 生成完了 ===")
    print(f"  処理時間          : {elapsed:.1f} 秒 ({total_tokens / max(elapsed, 0.1):,.0f} tokens/sec)")
    print(f"  books.parquet     : {len(books_rows):,} 作品 ({books_out.stat().st_size / (1024**2):.2f} MB)")
    print(f"  sentences.parquet : {total_sentences:,} 文 ({sentences_out.stat().st_size / (1024**2):.2f} MB)")
    print(
        f"  tokens_*.parquet  : {total_tokens:,} トークン / {len(token_files)} 分割ファイル "
        f"({sum(p.stat().st_size for p in token_files) / (1024**2):.2f} MB)"
    )
    print(f"  合計Parquetサイズ : {total_bytes / (1024**2):.2f} MB ({total_bytes / (1024**3):.2f} GB)")
    print(f"  スキップ(エラー)  : {len(build_errors):,} 件 -> {error_log_path}")


def main() -> None:
    cpu_default = max(1, min((os.cpu_count() or 4) - 2, 14))
    parser = argparse.ArgumentParser(
        description="青空文庫 著作権フリー全作品フルスケールParquet構築パイプライン"
    )
    parser.add_argument(
        "--mode",
        choices=["all", "fetch", "build"],
        default="all",
        help="fetch=全作品ZIP取得のみ, build=オフライン並列解析・Parquet生成のみ, all=両方",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="テスト用件数制限（未指定時は著作権フリー全作品を対象）",
    )
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--error-log", type=Path, default=Path("data/processed/error_log.txt"))
    parser.add_argument("--download-workers", type=int, default=8)
    parser.add_argument("--workers", type=int, default=cpu_default)
    parser.add_argument("--books-per-shard", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    catalog_csv = args.raw_dir / CATALOG_CSV_NAME
    manifest_path = args.raw_dir / "selected_books_full.json"

    if args.mode in ("all", "fetch"):
        catalog_csv = ensure_catalog_csv(args.raw_dir)
        raw_df, safe_books_df = load_and_filter_catalog(catalog_csv)
        print(f"[INFO] 著作権フリー＆ZIP有り全作品数: {len(safe_books_df):,} 作品")
        records = build_full_manifest_records(
            raw_df=raw_df,
            safe_books_df=safe_books_df,
            zips_dir=args.raw_dir / "zips",
            limit=args.limit,
        )
        manifest_path = run_fetch_phase(
            records=records,
            raw_dir=args.raw_dir,
            error_log_path=args.error_log,
            download_workers=args.download_workers,
        )

    if args.mode in ("all", "build"):
        run_build_phase(
            manifest_path=manifest_path,
            catalog_csv=catalog_csv,
            processed_dir=args.processed_dir,
            error_log_path=args.error_log,
            workers=args.workers,
            books_per_shard=args.books_per_shard,
            batch_size=args.batch_size,
        )


if __name__ == "__main__":
    main()
