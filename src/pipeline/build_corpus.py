"""青空文庫カタログCSVから著作権フリー作品を抽出し、形態素解析してParquetコーパスを生成するスクリプト。

絶対ルール（コンプライアンス）:
- カタログCSVの「作品著作権フラグ」が「なし」の作品のみを対象とする（人物著作権フラグ「あり」も完全除外）。
- 抽出処理およびParquet出力直前に必ず assert による強制検証を実行する。
- スキーマ定義（books.parquet, sentences.parquet, tokens.parquet）を厳守する。

使い方:
  1. 全工程を一括実行:
     python src/pipeline/build_corpus.py --limit 100
  2. ダウンロードとオフライン構築を分離実行:
     python src/pipeline/build_corpus.py --mode fetch --limit 100
     python src/pipeline/build_corpus.py --mode build --limit 100
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fugashi
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from tqdm import tqdm

# パッケージ外から直接スクリプト実行された場合にも対応
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.pipeline.text_cleaner import extract_clean_sentences

CATALOG_ZIP_URL = "https://www.aozora.gr.jp/index_pages/list_person_all_extended_utf8.zip"
CATALOG_CSV_NAME = "list_person_all_extended_utf8.csv"
USER_AGENT = "AozoraCorpusBuilder/0.1 (research-prototype; public-domain-only)"

# 初期100作品スモールスタートで多様な日本文学・随筆等を網羅するための優先定番著者リスト
# （著作権フラグ「なし」のフィルタを通過した作品のみから選出される）
FEATURED_AUTHORS = [
    "夏目漱石",
    "芥川竜之介",
    "太宰治",
    "宮沢賢治",
    "森鴎外",
    "梶井基次郎",
    "中島敦",
    "坂口安吾",
    "江戸川乱歩",
    "寺田寅彦",
    "小川未明",
    "夢野久作",
    "新美南吉",
    "泉鏡花",
    "樋口一葉",
    "島崎藤村",
    "国木田独歩",
    "谷崎潤一郎",
    "志賀直哉",
    "有島武郎",
    "菊池寛",
    "山本周五郎",
    "岡本綺堂",
    "豊島与志雄",
    "宮本百合子",
    "林芙美子",
    "与謝野晶子",
    "石川啄木",
    "中原中也",
    "萩原朔太郎",
    "中谷宇吉郎",
    "福沢諭吉",
    "新渡戸稲造",
    "柳田国男",
    "折口信夫",
    "九鬼周造",
    "西田幾多郎",
    "魯迅",
    "織田作之助",
    "太宰治",
]

# PyArrow 厳密スキーマ定義（GEMINI.md 準拠）
BOOKS_SCHEMA = pa.schema(
    [
        ("book_id", pa.int64()),
        ("title", pa.string()),
        ("author", pa.string()),
        ("author_birth_year", pa.int32()),
        ("published_year", pa.int32()),
        ("ndc", pa.string()),
        ("card_url", pa.string()),
        ("subcorpus", pa.string()),
    ]
)

SENTENCES_SCHEMA = pa.schema(
    [
        ("sentence_id", pa.int64()),
        ("book_id", pa.int64()),
        ("text", pa.string()),
    ]
)

TOKENS_SCHEMA = pa.schema(
    [
        ("sentence_id", pa.int64()),
        ("token_index", pa.int32()),
        ("start_pos", pa.int32()),
        ("end_pos", pa.int32()),
        ("surface", pa.string()),
        ("lemma", pa.string()),
        ("lemma_reading", pa.string()),
        ("pos", pa.string()),
        ("ctype", pa.string()),
        ("cform", pa.string()),
        ("goshu", pa.string()),
    ]
)

_YEAR_RE = re.compile(r"(1[5-9]\d{2}|20[0-2]\d)")


def _parse_year(*candidates: str) -> Optional[int]:
    """候補文字列から最初に現れる妥当な4桁西暦年を抽出する。"""
    for text in candidates:
        if not text:
            continue
        m = _YEAR_RE.search(text)
        if m:
            return int(m.group(1))
    return None


def _normalize_ndc(raw_ndc: str) -> str:
    """分類番号（例: 'NDC 913'）を正規化する。"""
    cleaned = raw_ndc.strip()
    if cleaned.upper().startswith("NDC"):
        cleaned = cleaned[3:].strip()
    # 先頭の分類コード（複数記載の場合は最初のコード）を保持
    return cleaned


def _format_author(sei: str, mei: str) -> str:
    sei = sei.strip()
    mei = mei.strip()
    if sei and mei:
        # カタカナのみ（海外著者等）の場合は中黒またはスペースではなくスペース結合
        if re.fullmatch(r"[ァ-ヶー・]+", sei) and re.fullmatch(r"[ァ-ヶー・]+", mei):
            return f"{sei} {mei}"
        return f"{sei}{mei}"
    return sei or mei


def ensure_catalog_csv(raw_dir: Path, force_download: bool = False) -> Path:
    """青空文庫カタログCSVをダウンロード・展開する（キャッシュ済みの場合は再利用）。"""
    raw_dir.mkdir(parents=True, exist_ok=True)
    csv_path = raw_dir / CATALOG_CSV_NAME
    if csv_path.exists() and not force_download:
        print(f"[INFO] 既存のカタログCSVを使用します: {csv_path}")
        return csv_path

    print(f"[INFO] 青空文庫カタログCSVをダウンロード中: {CATALOG_ZIP_URL}")
    resp = requests.get(CATALOG_ZIP_URL, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(raw_dir)
    assert csv_path.exists(), f"ZIP展開後に {csv_path} が見つかりません。"
    print(f"[INFO] カタログCSVを取得しました: {csv_path}")
    return csv_path


def load_and_filter_catalog(catalog_csv: Path) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """カタログCSVを読み込み、著作権フラグ「なし」のみを厳格に抽出する。

    Returns:
        (raw_df, safe_author_books_df)
    """
    raw_df = pd.read_csv(catalog_csv, dtype=str, keep_default_na=False)
    required_cols = [
        "作品ID",
        "作品名",
        "分類番号",
        "文字遣い種別",
        "作品著作権フラグ",
        "図書カードURL",
        "姓",
        "名",
        "役割フラグ",
        "生年月日",
        "人物著作権フラグ",
        "初出",
        "底本初版発行年1",
        "底本の親本初版発行年1",
        "テキストファイルURL",
    ]
    missing = [c for c in required_cols if c not in raw_df.columns]
    assert not missing, f"カタログCSVに必須列がありません: {missing}"

    # 同一「作品ID」に紐づく全レコード（著者・翻訳者・校訂者など）で
    # 1件でも「作品著作権フラグ != 'なし'」または「人物著作権フラグ == 'あり'」がある作品IDを完全除外
    unsafe_book_ids = set(
        raw_df.loc[
            (raw_df["作品著作権フラグ"].str.strip() != "なし")
            | (raw_df["人物著作権フラグ"].str.strip() == "あり"),
            "作品ID",
        ]
    )

    safe_all_rows = raw_df[~raw_df["作品ID"].isin(unsafe_book_ids)].copy()

    # CRITICAL ASSERTION: 著作権フラグ「なし」以外の混入を強制チェック
    assert (safe_all_rows["作品著作権フラグ"].str.strip() == "なし").all(), (
        "CRITICAL: 作品著作権フラグが「なし」以外のレコードが残存しています！"
    )
    assert not (safe_all_rows["作品著作権フラグ"].str.strip() == "あり").any(), (
        "CRITICAL: 作品著作権フラグ「あり」が混入しています！"
    )
    assert not (safe_all_rows["人物著作権フラグ"].str.strip() == "あり").any(), (
        "CRITICAL: 人物著作権フラグ「あり」が混入しています！"
    )

    # 著者行かつテキストZIPおよび図書カードURLが存在する作品に絞り、作品IDで重複排除
    books_df = safe_all_rows[
        (safe_all_rows["役割フラグ"].str.strip() == "著者")
        & (safe_all_rows["テキストファイルURL"].str.strip().str.endswith(".zip"))
        & (safe_all_rows["図書カードURL"].str.strip() != "")
    ].drop_duplicates(subset=["作品ID"], keep="first").copy()

    books_df["author_full"] = [
        _format_author(s, m) for s, m in zip(books_df["姓"], books_df["名"])
    ]
    books_df["book_id_int"] = books_df["作品ID"].astype(int)

    # 再度 assert で二重検証
    assert (books_df["作品著作権フラグ"].str.strip() == "なし").all(), (
        "CRITICAL: 抽出後の作品テーブルに著作権フラグ「なし」以外が含まれています！"
    )
    return raw_df, books_df


def select_candidate_books(
    books_df: pd.DataFrame,
    raw_df: pd.DataFrame,
    limit: int,
    max_per_author: int = 3,
    buffer_count: int = 25,
) -> pd.DataFrame:
    """多様な著者・ジャンルから決定論的に候補作品を選出する（新字新仮名を優先）。"""
    target_candidates = limit + buffer_count

    # 現代語形態素解析（unidic-lite）に適した「新字新仮名」を優先しつつ、足りなければ全体から補完
    shinji_df = books_df[books_df["文字遣い種別"].str.strip() == "新字新仮名"].copy()
    if len(shinji_df) < target_candidates:
        pool_df = books_df.copy()
    else:
        pool_df = shinji_df

    # 決定論的な並び順: 定番著者リストの順 -> 作品数が多い著者順 -> book_id 昇順
    featured_rank = {name: idx for idx, name in enumerate(dict.fromkeys(FEATURED_AUTHORS))}
    author_counts = pool_df["author_full"].value_counts().to_dict()

    pool_df["_featured_rank"] = pool_df["author_full"].map(lambda a: featured_rank.get(a, 9999))
    pool_df["_author_count_neg"] = pool_df["author_full"].map(lambda a: -author_counts.get(a, 0))
    pool_df = pool_df.sort_values(
        by=["_featured_rank", "_author_count_neg", "book_id_int"],
        ascending=[True, True, True],
    )

    selected_indices: List[int] = []
    per_author_counter: Dict[str, int] = {}

    for idx, row in pool_df.iterrows():
        author = row["author_full"]
        if per_author_counter.get(author, 0) >= max_per_author:
            continue
        selected_indices.append(idx)
        per_author_counter[author] = per_author_counter.get(author, 0) + 1
        if len(selected_indices) >= target_candidates:
            break

    # 上限に達しない場合は著者上限を緩和して補充
    if len(selected_indices) < target_candidates:
        selected_set = set(selected_indices)
        for idx in pool_df.index:
            if idx not in selected_set:
                selected_indices.append(idx)
                if len(selected_indices) >= target_candidates:
                    break

    candidates = pool_df.loc[selected_indices].copy()

    # CRITICAL ASSERTION: 選出した候補全件を元カタログCSVの全行と照合して著作権フラグ「なし」を再検証
    cand_ids = set(candidates["作品ID"])
    raw_matched = raw_df[raw_df["作品ID"].isin(cand_ids)]
    assert (raw_matched["作品著作権フラグ"].str.strip() == "なし").all(), (
        "CRITICAL: 選出候補に元カタログで著作権フラグ「なし」以外の作品が含まれています！"
    )
    assert not (raw_matched["人物著作権フラグ"].str.strip() == "あり").any(), (
        "CRITICAL: 選出候補に人物著作権フラグ「あり」の作品が含まれています！"
    )

    return candidates.drop(columns=["_featured_rank", "_author_count_neg"])


def download_book_zips(
    candidates: pd.DataFrame,
    raw_dir: Path,
    limit: int,
    sleep_sec: float = 0.15,
) -> Path:
    """候補作品のテキストZIPをダウンロードし、成功した先頭 `limit` 作品のリストをマニフェスト保存する。"""
    zips_dir = raw_dir / "zips"
    zips_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = raw_dir / f"selected_books_{limit}.json"

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    manifest_records: List[Dict[str, object]] = []

    pbar = tqdm(total=limit, desc="作品ZIP取得", unit="作品")
    for _, row in candidates.iterrows():
        if len(manifest_records) >= limit:
            break

        # 念のためダウンロード直前にも著作権フラグを強制検証
        assert row["作品著作権フラグ"].strip() == "なし", (
            f"CRITICAL: 著作権フラグ違反を検知: 作品ID={row['作品ID']}"
        )

        book_id_int = int(row["book_id_int"])
        url = row["テキストファイルURL"].strip()
        zip_path = zips_dir / f"{book_id_int:06d}.zip"

        if not zip_path.exists():
            try:
                resp = session.get(url, timeout=30)
                resp.raise_for_status()
                # ZIPとして壊れていないか検証してから保存
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    txt_names = [n for n in zf.namelist() if n.lower().endswith(".txt")]
                    if not txt_names:
                        continue
                zip_path.write_bytes(resp.content)
                if sleep_sec > 0:
                    time.sleep(sleep_sec)
            except Exception as exc:
                print(f"[WARN] ダウンロード失敗（スキップ） book_id={book_id_int} ({row['作品名']}): {exc}")
                continue
        else:
            # 既存キャッシュの健全性チェック
            try:
                with zipfile.ZipFile(zip_path) as zf:
                    if not any(n.lower().endswith(".txt") for n in zf.namelist()):
                        continue
            except zipfile.BadZipFile:
                zip_path.unlink(missing_ok=True)
                continue

        # クリーニング後に少なくとも1文以上抽出できるか事前確認
        try:
            raw_bytes = _read_txt_from_zip(zip_path)
            sentences = extract_clean_sentences(raw_bytes)
            if not sentences:
                print(f"[WARN] 本文が抽出できませんでした（スキップ） book_id={book_id_int} ({row['作品名']})")
                continue
        except Exception as exc:
            print(f"[WARN] テキスト読込エラー（スキップ） book_id={book_id_int}: {exc}")
            continue

        manifest_records.append(
            {
                "book_id": book_id_int,
                "work_id_str": row["作品ID"],
                "title": row["作品名"].strip(),
                "author": row["author_full"],
                "author_birth_year": _parse_year(row["生年月日"]),
                "published_year": _parse_year(
                    row["初出"],
                    row["底本の親本初版発行年1"],
                    row["底本初版発行年1"],
                ),
                "ndc": _normalize_ndc(row["分類番号"]),
                "card_url": row["図書カードURL"].strip(),
                "subcorpus": row["文字遣い種別"].strip() or "その他",
                "copyright_flag": row["作品著作権フラグ"].strip(),
                "zip_path": str(zip_path.as_posix()),
            }
        )
        pbar.update(1)
    pbar.close()

    assert len(manifest_records) == limit, (
        f"目標件数 {limit} 作品に到達できませんでした（取得数={len(manifest_records)}）。"
    )
    assert all(r["copyright_flag"] == "なし" for r in manifest_records), (
        "CRITICAL: マニフェスト内に著作権フラグ「なし」以外が混入しています！"
    )

    manifest_path.write_text(
        json.dumps(manifest_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[INFO] {len(manifest_records)} 作品のマニフェストを保存しました: {manifest_path}")
    return manifest_path


def _read_txt_from_zip(zip_path: Path) -> bytes:
    """ZIPファイル内から最大の .txt ファイルのバイト列を読み込む。"""
    with zipfile.ZipFile(zip_path, "r") as zf:
        txt_infos = [info for info in zf.infolist() if info.filename.lower().endswith(".txt")]
        if not txt_infos:
            raise ValueError(f"ZIP内に .txt ファイルがありません: {zip_path}")
        # 複数 .txt がある場合はファイルサイズ最大のものを本文とみなす
        main_info = max(txt_infos, key=lambda info: info.file_size)
        return zf.read(main_info.filename)


def _clean_feature(value: Optional[str]) -> str:
    if value is None or value == "*":
        return ""
    return value


def tokenize_sentence(
    tagger: fugashi.Tagger,
    sentence_id: int,
    sentence_text: str,
) -> List[Dict[str, object]]:
    """1文を UniDic (fugashi + unidic-lite) で形態素解析し、スキーマ準拠のトークン辞書リストを返す。"""
    tokens: List[Dict[str, object]] = []
    cursor = 0
    token_index = 0

    for word in tagger(sentence_text):
        surface = word.surface
        if not surface:
            continue

        # MeCabは空白をスキップするため、現在位置から厳密に文字位置を検索する
        start_pos = sentence_text.find(surface, cursor)
        assert start_pos != -1, (
            f"トークン位置の特定に失敗しました: sentence_id={sentence_id}, "
            f"surface={surface!r}, cursor={cursor}, text={sentence_text!r}"
        )
        end_pos = start_pos + len(surface)
        assert sentence_text[start_pos:end_pos] == surface
        cursor = end_pos

        f = word.feature
        pos_parts = [p for p in (f.pos1, f.pos2, f.pos3, f.pos4) if p and p != "*"]
        pos = "-".join(pos_parts) if pos_parts else "不明"

        lemma = _clean_feature(f.lemma) or surface
        lemma_reading = _clean_feature(f.lForm)
        ctype = _clean_feature(f.cType)
        cform = _clean_feature(f.cForm)
        goshu = _clean_feature(f.goshu)

        tokens.append(
            {
                "sentence_id": sentence_id,
                "token_index": token_index,
                "start_pos": start_pos,
                "end_pos": end_pos,
                "surface": surface,
                "lemma": lemma,
                "lemma_reading": lemma_reading,
                "pos": pos,
                "ctype": ctype,
                "cform": cform,
                "goshu": goshu,
            }
        )
        token_index += 1

    return tokens


def build_parquets(
    manifest_path: Path,
    catalog_csv: Path,
    processed_dir: Path,
) -> None:
    """マニフェストに基づき形態素解析を実行し、3つのParquetファイルを生成する（完全オフライン）。"""
    assert manifest_path.exists(), f"マニフェストが存在しません: {manifest_path}"
    assert catalog_csv.exists(), f"カタログCSVが存在しません: {catalog_csv}"

    manifest_records: List[Dict[str, object]] = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )

    # CRITICAL ASSERTION: ビルド直前に元カタログCSVと突合して著作権フラグ「なし」を再検証
    raw_df = pd.read_csv(catalog_csv, dtype=str, keep_default_na=False)
    manifest_work_ids = {str(r["work_id_str"]) for r in manifest_records}
    matched_raw = raw_df[raw_df["作品ID"].isin(manifest_work_ids)]
    assert len(matched_raw) > 0, "元カタログとの照合結果が空です。"
    assert (matched_raw["作品著作権フラグ"].str.strip() == "なし").all(), (
        "CRITICAL: ビルド対象に作品著作権フラグ「なし」以外が含まれています！"
    )
    assert not (matched_raw["人物著作権フラグ"].str.strip() == "あり").any(), (
        "CRITICAL: ビルド対象に人物著作権フラグ「あり」が含まれています！"
    )
    print(
        f"[OK] ビルド前コンプライアンス検証通過: 全 {len(manifest_records)} 作品の著作権フラグ「なし」を確認"
    )

    processed_dir.mkdir(parents=True, exist_ok=True)
    books_out = processed_dir / "books.parquet"
    sentences_out = processed_dir / "sentences.parquet"
    tokens_out = processed_dir / "tokens.parquet"

    tagger = fugashi.Tagger()

    # 1. books.parquet の書き出し
    books_rows = [
        {
            "book_id": int(r["book_id"]),
            "title": str(r["title"]),
            "author": str(r["author"]),
            "author_birth_year": r["author_birth_year"],
            "published_year": r["published_year"],
            "ndc": str(r["ndc"]),
            "card_url": str(r["card_url"]),
            "subcorpus": str(r["subcorpus"]),
        }
        for r in manifest_records
    ]
    books_table = pa.Table.from_pylist(books_rows, schema=BOOKS_SCHEMA)
    pq.write_table(books_table, books_out, compression="zstd")

    # 2. sentences.parquet と tokens.parquet をストリーミング書き出し（大規模スケール対応）
    sent_writer = pq.ParquetWriter(sentences_out, SENTENCES_SCHEMA, compression="zstd")
    token_writer = pq.ParquetWriter(tokens_out, TOKENS_SCHEMA, compression="zstd")

    sentence_id_seq = 1
    total_sentences = 0
    total_tokens = 0
    sent_buffer: List[Dict[str, object]] = []
    token_buffer: List[Dict[str, object]] = []

    SENT_FLUSH_SIZE = 5_000
    TOKEN_FLUSH_SIZE = 100_000

    try:
        for rec in tqdm(manifest_records, desc="形態素解析 & Parquet生成", unit="作品"):
            book_id = int(rec["book_id"])
            zip_path = Path(str(rec["zip_path"]))
            raw_bytes = _read_txt_from_zip(zip_path)
            sentences = extract_clean_sentences(raw_bytes)

            for sent_text in sentences:
                tokens = tokenize_sentence(tagger, sentence_id_seq, sent_text)
                if not tokens:
                    # トークンが0件の文はスキップし、sentences と tokens の1対多整合性を厳密に保つ
                    continue

                # token_index の連番をインラインでも保証
                assert tokens[0]["token_index"] == 0
                assert tokens[-1]["token_index"] == len(tokens) - 1

                sent_buffer.append(
                    {
                        "sentence_id": sentence_id_seq,
                        "book_id": book_id,
                        "text": sent_text,
                    }
                )
                token_buffer.extend(tokens)

                sentence_id_seq += 1
                total_sentences += 1
                total_tokens += len(tokens)

                if len(sent_buffer) >= SENT_FLUSH_SIZE:
                    sent_writer.write_table(pa.Table.from_pylist(sent_buffer, schema=SENTENCES_SCHEMA))
                    sent_buffer.clear()

                if len(token_buffer) >= TOKEN_FLUSH_SIZE:
                    token_writer.write_table(pa.Table.from_pylist(token_buffer, schema=TOKENS_SCHEMA))
                    token_buffer.clear()

        if sent_buffer:
            sent_writer.write_table(pa.Table.from_pylist(sent_buffer, schema=SENTENCES_SCHEMA))
            sent_buffer.clear()
        if token_buffer:
            token_writer.write_table(pa.Table.from_pylist(token_buffer, schema=TOKENS_SCHEMA))
            token_buffer.clear()
    finally:
        sent_writer.close()
        token_writer.close()

    print("\n=== Parquet生成完了 ===")
    print(f"  books.parquet     : {len(books_rows):,} 作品 -> {books_out}")
    print(f"  sentences.parquet : {total_sentences:,} 文 -> {sentences_out}")
    print(f"  tokens.parquet    : {total_tokens:,} トークン -> {tokens_out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="青空文庫コーパスParquet構築パイプライン")
    parser.add_argument(
        "--mode",
        choices=["all", "fetch", "build"],
        default="all",
        help="実行モード: fetch=カタログとZIP取得のみ, build=オフライン解析・Parquet出力のみ, all=両方",
    )
    parser.add_argument("--limit", type=int, default=100, help="抽出する作品数（デフォルト: 100）")
    parser.add_argument("--max-per-author", type=int, default=3, help="1著者あたりの上限作品数")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"), help="生データ保存先")
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed"), help="Parquet出力先")
    parser.add_argument("--sleep", type=float, default=0.15, help="ダウンロード間隔（秒）")
    args = parser.parse_args()

    catalog_csv = args.raw_dir / CATALOG_CSV_NAME
    manifest_path = args.raw_dir / f"selected_books_{args.limit}.json"

    if args.mode in ("all", "fetch"):
        catalog_csv = ensure_catalog_csv(args.raw_dir)
        raw_df, safe_books_df = load_and_filter_catalog(catalog_csv)
        print(f"[INFO] 著作権フリー＆ZIP有り作品数: {len(safe_books_df):,} 作品")
        candidates = select_candidate_books(
            safe_books_df,
            raw_df,
            limit=args.limit,
            max_per_author=args.max_per_author,
        )
        manifest_path = download_book_zips(
            candidates,
            raw_dir=args.raw_dir,
            limit=args.limit,
            sleep_sec=args.sleep,
        )

    if args.mode in ("all", "build"):
        build_parquets(
            manifest_path=manifest_path,
            catalog_csv=catalog_csv,
            processed_dir=args.processed_dir,
        )


if __name__ == "__main__":
    main()
