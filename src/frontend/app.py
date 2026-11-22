"""青空文庫「中納言風」短単位コーパス検索 Webアプリ（Streamlit プロトタイプ）。

起動方法:
    streamlit run src/frontend/app.py
"""

from __future__ import annotations

import html
import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

# ルートディレクトリをインポートパスへ追加（`streamlit run src/frontend/app.py` 対応）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.search_engine import (
    BibliographicFilter,
    CollocationCondition,
    CorpusSearchEngine,
    SearchQuery,
    SearchResult,
    TokenCondition,
)

PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

MATCH_MODE_LABELS = {
    "完全一致": "exact",
    "前方一致": "prefix",
    "部分一致": "contains",
    "正規表現": "regex",
}

DISTANCE_MODE_LABELS = {
    "直前 / 直後 (1語)": "adjacent",
    "ちょうど N 語": "exact",
    "1〜N 語以内": "within",
}

# 検索結果テーブルの日本語列名と内部カラム名の対応
DISPLAY_COLUMN_MAP: Dict[str, str] = {
    "作品名": "title",
    "著者": "author",
    "前文脈": "left_context",
    "キー": "key_text",
    "後文脈": "right_context",
    "語彙素": "lemma",
    "書字形出現形": "surface",
    "語彙素読み": "lemma_reading",
    "品詞": "pos",
    "活用型": "ctype",
    "活用形": "cform",
    "語種": "goshu",
    "NDC": "ndc",
    "出版年": "published_year",
    "著者生年": "author_birth_year",
    "サブコーパス": "subcorpus",
    "図書カードURL": "card_url",
    "文全文": "text",
}

DEFAULT_DISPLAY_COLUMNS: List[str] = [
    "作品名",
    "著者",
    "前文脈",
    "キー",
    "後文脈",
    "語彙素",
    "品詞",
    "活用形",
]


@st.cache_resource
def get_search_engine() -> CorpusSearchEngine:
    return CorpusSearchEngine(PROCESSED_DIR)


@st.cache_data(ttl=3600)
def load_corpus_stats() -> Dict[str, Any]:
    return get_search_engine().get_corpus_stats()


def _init_session_state() -> None:
    if "colloc_items" not in st.session_state:
        st.session_state["colloc_items"] = []
    if "colloc_seq" not in st.session_state:
        st.session_state["colloc_seq"] = 0
    if "last_result" not in st.session_state:
        st.session_state["last_result"] = None
    if "kwic_page" not in st.session_state:
        st.session_state["kwic_page"] = 1


def _add_collocation(direction: str) -> None:
    st.session_state["colloc_seq"] += 1
    cid = st.session_state["colloc_seq"]
    st.session_state["colloc_items"].append({"id": cid, "direction": direction})


def _remove_collocation(cid: int) -> None:
    st.session_state["colloc_items"] = [
        item for item in st.session_state["colloc_items"] if item["id"] != cid
    ]


def _clear_collocations() -> None:
    st.session_state["colloc_items"] = []


def _apply_preset(preset_name: str) -> None:
    """ワンクリック検索プリセットをフォーム状態に適用する。"""
    # キー項目リセット
    for k in (
        "key_lemma",
        "key_surface",
        "key_reading",
        "key_pos",
        "key_ctype",
        "key_cform",
        "key_goshu",
    ):
        st.session_state[k] = ""
    st.session_state["key_match_mode"] = "完全一致"
    st.session_state["colloc_items"] = []

    if preset_name == "verb_te":
        st.session_state["key_pos"] = "動詞-一般"
        st.session_state["key_cform"] = "連用形"
        _add_collocation("after")
        cid = st.session_state["colloc_items"][-1]["id"]
        st.session_state[f"colloc_dist_mode_{cid}"] = "直前 / 直後 (1語)"
        st.session_state[f"colloc_dist_{cid}"] = 1
        st.session_state[f"colloc_lemma_{cid}"] = "て"
        st.session_state[f"colloc_pos_{cid}"] = "助詞"
    elif preset_name == "kokoro_prev_pos":
        st.session_state["key_lemma"] = "心"
        _add_collocation("before")
        cid = st.session_state["colloc_items"][-1]["id"]
        st.session_state[f"colloc_dist_mode_{cid}"] = "ちょうど N 語"
        st.session_state[f"colloc_dist_{cid}"] = 2
        st.session_state[f"colloc_pos_{cid}"] = "助詞"
    elif preset_name == "hashiru":
        st.session_state["key_lemma"] = "走る"


def _build_display_dataframe(df: pd.DataFrame, selected_columns: List[str]) -> pd.DataFrame:
    """日本語列名へリネームした表示用DataFrameを生成する。"""
    cols_to_select = [DISPLAY_COLUMN_MAP[c] for c in selected_columns if c in DISPLAY_COLUMN_MAP]
    rename_map = {DISPLAY_COLUMN_MAP[c]: c for c in selected_columns if c in DISPLAY_COLUMN_MAP}
    return df[cols_to_select].rename(columns=rename_map)


def _to_utf8_bom_csv(df: pd.DataFrame, selected_columns: List[str]) -> bytes:
    """Excelで文字化けしない UTF-8 BOM付き CSV バイト列を生成する。"""
    export_cols = list(selected_columns)
    # コンプライアンス上、CSVにも出典リンク（図書カードURL）を含める
    if "図書カードURL" not in export_cols:
        export_cols.append("図書カードURL")
    export_df = _build_display_dataframe(df, export_cols)
    return export_df.to_csv(index=False).encode("utf-8-sig")


def _render_kwic_html_table(
    page_df: pd.DataFrame,
    selected_columns: List[str],
    start_row_no: int,
) -> str:
    """前文脈（右揃え）｜キー（赤字中央揃え）｜後文脈（左揃え）の中納言風KWIC HTMLテーブルを生成する。"""
    css = """
    <style>
    .kwic-wrapper {
        width: 100%;
        overflow-x: auto;
        border: 1px solid #d0d7de;
        border-radius: 6px;
        background: #ffffff;
    }
    table.kwic-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.9rem;
        line-height: 1.5;
        color: #1f2328;
    }
    table.kwic-table thead th {
        position: sticky;
        top: 0;
        background: #f6f8fa;
        border-bottom: 2px solid #d0d7de;
        padding: 8px 10px;
        text-align: left;
        white-space: nowrap;
        font-weight: 600;
    }
    table.kwic-table thead th.col-left-ctx {
        text-align: right;
    }
    table.kwic-table thead th.col-key {
        text-align: center;
        color: #c92a2a;
    }
    table.kwic-table tbody td {
        border-bottom: 1px solid #eaeef2;
        padding: 6px 10px;
        vertical-align: middle;
        white-space: nowrap;
    }
    table.kwic-table tbody tr:hover {
        background-color: #f8fafc;
    }
    table.kwic-table td.col-no {
        color: #6e7781;
        text-align: right;
        font-variant-numeric: tabular-nums;
    }
    table.kwic-table td.col-left-ctx {
        text-align: right;
        font-family: "Yu Gothic UI", "Hiragino Sans", sans-serif;
        padding-right: 6px;
        color: #334155;
    }
    table.kwic-table td.col-key {
        text-align: center;
        font-weight: 700;
        color: #c92a2a;
        background-color: #fff5f5;
        border-left: 1px solid #ffc9c9;
        border-right: 1px solid #ffc9c9;
        padding: 6px 12px;
    }
    table.kwic-table td.col-right-ctx {
        text-align: left;
        font-family: "Yu Gothic UI", "Hiragino Sans", sans-serif;
        padding-left: 6px;
        color: #334155;
    }
    table.kwic-table td.col-fulltext {
        white-space: normal;
        min-width: 320px;
    }
    table.kwic-table a {
        color: #0969da;
        text-decoration: none;
    }
    table.kwic-table a:hover {
        text-decoration: underline;
    }
    </style>
    """

    header_cells = ['<th class="col-no">#</th>']
    for col in selected_columns:
        cls = ""
        if col == "前文脈":
            cls = ' class="col-left-ctx"'
        elif col == "キー":
            cls = ' class="col-key"'
        elif col == "後文脈":
            cls = ' class="col-right-ctx"'
        header_cells.append(f"<th{cls}>{html.escape(col)}</th>")

    body_rows: List[str] = []
    for idx, row in enumerate(page_df.to_dict(orient="records"), start=start_row_no):
        cells = [f'<td class="col-no">{idx}</td>']
        card_url = str(row.get("card_url") or "")
        for col in selected_columns:
            internal = DISPLAY_COLUMN_MAP[col]
            raw_val = row.get(internal, "")
            val_str = "" if pd.isna(raw_val) else str(raw_val)
            escaped = html.escape(val_str)

            if col == "作品名" and card_url:
                safe_url = html.escape(card_url, quote=True)
                cells.append(
                    f'<td><a href="{safe_url}" target="_blank" rel="noopener noreferrer" '
                    f'title="青空文庫 図書カードを開く">{escaped}</a></td>'
                )
            elif col == "図書カードURL" and card_url:
                safe_url = html.escape(card_url, quote=True)
                cells.append(
                    f'<td><a href="{safe_url}" target="_blank" rel="noopener noreferrer">図書カード</a></td>'
                )
            elif col == "前文脈":
                cells.append(f'<td class="col-left-ctx">{escaped}</td>')
            elif col == "キー":
                cells.append(f'<td class="col-key">{escaped}</td>')
            elif col == "後文脈":
                cells.append(f'<td class="col-right-ctx">{escaped}</td>')
            elif col == "文全文":
                cells.append(f'<td class="col-fulltext">{escaped}</td>')
            else:
                cells.append(f"<td>{escaped}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    return (
        css
        + '<div class="kwic-wrapper"><table class="kwic-table">'
        + "<thead><tr>"
        + "".join(header_cells)
        + "</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table></div>"
    )


def main() -> None:
    st.set_page_config(
        page_title="青空文庫 中納言風コーパス検索",
        page_icon="📚",
        layout="wide",
    )
    _init_session_state()

    try:
        engine = get_search_engine()
        stats = load_corpus_stats()
    except FileNotFoundError as exc:
        st.error(
            f"Parquetデータが見つかりません: {exc}\n\n"
            "先に `python src/pipeline/build_corpus.py --limit 100` を実行してコーパスを構築してください。"
        )
        return

    # === ヘッダ & コーパス統計 ===
    st.title("📚 青空文庫「中納言風」短単位コーパス検索")
    st.caption(
        "UniDic準拠の短単位情報（語彙素・品詞・活用形・語種）と `token_index` ベースの高速共起検索（Parquet + DuckDB）"
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("収録作品数（著作権フリー）", f"{stats['book_count']:,} 作品")
    m2.metric("著者数", f"{stats['author_count']:,} 名")
    m3.metric("総文数", f"{stats['sentence_count']:,} 文")
    m4.metric("総短単位（トークン）数", f"{stats['token_count']:,} 語")

    # クイックプリセット
    with st.container():
        p_cols = st.columns([1.2, 2.2, 2.2, 2.0, 2.4])
        p_cols[0].markdown("**検索例:**")
        if p_cols[1].button("動詞-一般(連用形) + 直後「て」", width="stretch"):
            _apply_preset("verb_te")
            st.rerun()
        if p_cols[2].button("2語前(助詞) + 語彙素「心」", width="stretch"):
            _apply_preset("kokoro_prev_pos")
            st.rerun()
        if p_cols[3].button("語彙素「走る」単一検索", width="stretch"):
            _apply_preset("hashiru")
            st.rerun()

    st.divider()

    # ==========================================================
    # ① 検索条件ビルダー
    # ==========================================================
    st.subheader("1. 検索条件ビルダー（短単位検索）")

    pos_choices = [""] + stats["pos_options"]
    ctype_choices = [""] + stats["ctype_options"]
    cform_choices = [""] + stats["cform_options"]
    goshu_choices = [""] + stats["goshu_options"]

    # --- キー（中心語）条件 ---
    with st.container(border=True):
        st.markdown("#### 🎯 キー（中心語）条件（入力項目はすべて AND 結合）")
        k_row1 = st.columns([2, 2, 2, 1.5])
        key_lemma = k_row1[0].text_input(
            "語彙素 (lemma)",
            key="key_lemma",
            placeholder="例: 走る, 心, 有る",
        )
        key_surface = k_row1[1].text_input(
            "書字形出現形 / 表層形 (surface)",
            key="key_surface",
            placeholder="例: 走っ, こころ",
        )
        key_reading = k_row1[2].text_input(
            "語彙素読み (lemma_reading)",
            key="key_reading",
            placeholder="例: ハシル, ココロ",
        )
        key_match_label = k_row1[3].selectbox(
            "語彙素/表層/読みの一致",
            options=list(MATCH_MODE_LABELS.keys()),
            key="key_match_mode",
        )

        k_row2 = st.columns([2.2, 2.0, 2.0, 1.3])
        key_pos = k_row2[0].selectbox(
            "品詞 (pos) ※階層一致",
            options=pos_choices,
            key="key_pos",
            help="「動詞」や「動詞-一般」のように上位階層を選ぶと下位分類も一括ヒットします。",
        )
        key_ctype = k_row2[1].selectbox(
            "活用型 (ctype) ※階層一致",
            options=ctype_choices,
            key="key_ctype",
        )
        key_cform = k_row2[2].selectbox(
            "活用形 (cform) ※階層一致",
            options=cform_choices,
            key="key_cform",
            help="「連用形」を選ぶと「連用形-一般」「連用形-促音便」等にマッチします。",
        )
        key_goshu = k_row2[3].selectbox(
            "語種 (goshu)",
            options=goshu_choices,
            key="key_goshu",
        )

    # --- 共起条件の動的追加ボタン ---
    colloc_hdr = st.columns([3.5, 1.8, 1.8, 1.6])
    colloc_hdr[0].markdown("#### 🔗 共起条件（同一文内 `token_index` 結合）")
    if colloc_hdr[1].button("＋ 前方共起を追加", width="stretch"):
        _add_collocation("before")
        st.rerun()
    if colloc_hdr[2].button("＋ 後方共起を追加", width="stretch"):
        _add_collocation("after")
        st.rerun()
    if colloc_hdr[3].button(
        "共起を全クリア",
        width="stretch",
        disabled=len(st.session_state["colloc_items"]) == 0,
    ):
        _clear_collocations()
        st.rerun()

    # --- 各共起条件ブロックの描画 ---
    collocation_conditions: List[CollocationCondition] = []
    for idx, item in enumerate(st.session_state["colloc_items"], start=1):
        cid = item["id"]
        direction = item["direction"]
        dir_label = "◀ 前方共起（キーより前）" if direction == "before" else "▶ 後方共起（キーより後）"

        with st.container(border=True):
            top_cols = st.columns([4.5, 2.2, 1.5, 1.0])
            top_cols[0].markdown(f"**{dir_label} #{idx}**")
            dist_mode_label = top_cols[1].selectbox(
                "距離指定タイプ",
                options=list(DISTANCE_MODE_LABELS.keys()),
                key=f"colloc_dist_mode_{cid}",
                label_visibility="collapsed",
            )
            dist_mode_code = DISTANCE_MODE_LABELS[dist_mode_label]

            if dist_mode_code == "adjacent":
                distance_val = 1
                top_cols[2].text_input(
                    "距離",
                    value="直前 (1語)" if direction == "before" else "直後 (1語)",
                    disabled=True,
                    key=f"colloc_dist_disp_{cid}",
                    label_visibility="collapsed",
                )
                actual_distance_mode = "exact"
            else:
                dist_key = f"colloc_dist_{cid}"
                if dist_key not in st.session_state:
                    st.session_state[dist_key] = 1
                distance_val = int(
                    top_cols[2].number_input(
                        "距離 N (1〜10語)",
                        min_value=1,
                        max_value=10,
                        step=1,
                        key=dist_key,
                        label_visibility="collapsed",
                    )
                )
                actual_distance_mode = dist_mode_code

            if top_cols[3].button("削除", key=f"del_colloc_{cid}", width="stretch"):
                _remove_collocation(cid)
                st.rerun()

            c_row1 = st.columns([2, 2, 2.2, 2])
            c_lemma = c_row1[0].text_input(
                "語彙素",
                key=f"colloc_lemma_{cid}",
                placeholder="例: て, を, の",
            )
            c_surface = c_row1[1].text_input(
                "書字形出現形",
                key=f"colloc_surface_{cid}",
                placeholder="表層形",
            )
            c_pos = c_row1[2].selectbox(
                "品詞 ※階層一致",
                options=pos_choices,
                key=f"colloc_pos_{cid}",
            )
            c_cform = c_row1[3].selectbox(
                "活用形 ※階層一致",
                options=cform_choices,
                key=f"colloc_cform_{cid}",
            )

            with st.expander("詳細条件（読み・活用型・語種・一致方式）", expanded=False):
                c_row2 = st.columns([2, 2, 1.5, 1.5])
                c_reading = c_row2[0].text_input("語彙素読み", key=f"colloc_reading_{cid}")
                c_ctype = c_row2[1].selectbox("活用型", options=ctype_choices, key=f"colloc_ctype_{cid}")
                c_goshu = c_row2[2].selectbox("語種", options=goshu_choices, key=f"colloc_goshu_{cid}")
                c_match_label = c_row2[3].selectbox(
                    "一致方式",
                    options=list(MATCH_MODE_LABELS.keys()),
                    key=f"colloc_match_{cid}",
                )

            collocation_conditions.append(
                CollocationCondition(
                    direction=direction,  # type: ignore[arg-type]
                    distance=distance_val,
                    distance_mode=actual_distance_mode,  # type: ignore[arg-type]
                    condition=TokenCondition(
                        lemma=c_lemma,
                        surface=c_surface,
                        lemma_reading=c_reading,
                        pos=c_pos,
                        ctype=c_ctype,
                        cform=c_cform,
                        goshu=c_goshu,
                        match_mode=MATCH_MODE_LABELS[c_match_label],  # type: ignore[arg-type]
                    ),
                )
            )

    # --- 書誌フィルタ & 検索オプション ---
    with st.expander("📖 書誌絞り込み・表示設定（任意）", expanded=False):
        b_row1 = st.columns([2.5, 2, 1.5, 1.5])
        selected_authors = b_row1[0].multiselect("著者", options=stats["authors"])
        title_query = b_row1[1].text_input("作品名（部分一致）", placeholder="例: 坊っちゃん")
        selected_subcorpora = b_row1[2].multiselect("サブコーパス", options=stats["subcorpora"])
        ndc_prefix = b_row1[3].text_input("NDC前方一致", placeholder="例: 913")

        b_row2 = st.columns([1.5, 1.5, 2, 2])
        min_year_default = stats["min_published_year"] or 1850
        max_year_default = stats["max_published_year"] or 2025
        use_year_filter = b_row2[0].checkbox("出版年で絞り込む", value=False)
        if use_year_filter:
            year_range = b_row2[1].slider(
                "出版年範囲",
                min_value=min_year_default,
                max_value=max_year_default,
                value=(min_year_default, max_year_default),
            )
            pub_min, pub_max = year_range[0], year_range[1]
        else:
            b_row2[1].caption("出版年フィルタ: 無効")
            pub_min, pub_max = None, None

        max_rows = int(
            b_row2[2].selectbox(
                "最大取得件数",
                options=[100, 500, 1000, 3000, 5000],
                index=2,
            )
        )
        context_chars = int(
            b_row2[3].slider(
                "KWIC前後文脈の表示文字数",
                min_value=10,
                max_value=60,
                value=30,
                step=5,
            )
        )

    # --- 検索実行ボタン ---
    search_clicked = st.button("🔍 検索を実行", type="primary", width="stretch")

    if search_clicked:
        key_cond = TokenCondition(
            lemma=key_lemma,
            surface=key_surface,
            lemma_reading=key_reading,
            pos=key_pos,
            ctype=key_ctype,
            cform=key_cform,
            goshu=key_goshu,
            match_mode=MATCH_MODE_LABELS[key_match_label],  # type: ignore[arg-type]
        )
        if key_cond.is_empty():
            st.warning("キー（中心語）の検索条件を1つ以上入力または選択してください。")
        else:
            query = SearchQuery(
                key=key_cond,
                collocations=collocation_conditions,
                bib=BibliographicFilter(
                    authors=selected_authors,
                    title_query=title_query,
                    subcorpora=selected_subcorpora,
                    ndc_prefix=ndc_prefix,
                    published_year_min=pub_min,
                    published_year_max=pub_max,
                ),
                limit=max_rows,
            )
            try:
                with st.spinner("DuckDBでParquetコーパスを検索中..."):
                    result: SearchResult = engine.search(query, context_chars=context_chars)
                st.session_state["last_result"] = result
                st.session_state["kwic_page"] = 1
            except Exception as exc:
                st.error(f"検索クエリの実行中にエラーが発生しました: {exc}")

    # ==========================================================
    # ② 検索結果（KWICテーブル & 表示列切り替え & CSVダウンロード）
    # ==========================================================
    result: SearchResult | None = st.session_state.get("last_result")
    if result is not None:
        st.divider()
        st.subheader("2. 検索結果（KWIC）")

        fetched_count = len(result.df)
        info_cols = st.columns([2.2, 1.5, 2.3])
        info_cols[0].success(
            f"**総ヒット件数: {result.total_count:,} 件**（取得表示: {fetched_count:,} 件）"
        )
        info_cols[1].info(f"実行時間: **{result.elapsed_ms:.1f} ms**")

        selected_columns = st.multiselect(
            "表示する列を選択（並び順も反映されます）",
            options=list(DISPLAY_COLUMN_MAP.keys()),
            default=DEFAULT_DISPLAY_COLUMNS,
        )
        if not selected_columns:
            st.warning("表示する列を1つ以上選択してください。")
        elif result.df.empty:
            st.info("条件に一致する用例は見つかりませんでした。")
        else:
            csv_bytes = _to_utf8_bom_csv(result.df, selected_columns)
            info_cols[2].download_button(
                label=f"⬇️ CSVダウンロード（UTF-8 BOM付 / {fetched_count:,}件）",
                data=csv_bytes,
                file_name="aozora_kwic_results.csv",
                mime="text/csv",
                width="stretch",
            )

            tab_kwic, tab_df = st.tabs(
                ["📑 KWICビュー（中納言スタイル中央揃え）", "📊 データテーブル（st.dataframe）"]
            )

            with tab_kwic:
                page_size = 50
                total_pages = max(1, (fetched_count + page_size - 1) // page_size)
                if st.session_state.get("kwic_page", 1) > total_pages:
                    st.session_state["kwic_page"] = 1
                pg_cols = st.columns([1.5, 4.5, 2])
                current_page = int(
                    pg_cols[0].number_input(
                        f"ページ (1〜{total_pages})",
                        min_value=1,
                        max_value=total_pages,
                        step=1,
                        key="kwic_page",
                    )
                )
                start_idx = (current_page - 1) * page_size
                end_idx = min(start_idx + page_size, fetched_count)
                pg_cols[1].caption(
                    f"{start_idx + 1:,} 〜 {end_idx:,} 件目を表示中（作品名クリックで青空文庫の図書カードへ移動します）"
                )
                page_df = result.df.iloc[start_idx:end_idx]
                st.markdown(
                    _render_kwic_html_table(page_df, selected_columns, start_row_no=start_idx + 1),
                    unsafe_allow_html=True,
                )

            with tab_df:
                display_df = _build_display_dataframe(result.df, selected_columns)
                column_cfg: Dict[str, Any] = {}
                if "図書カードURL" in display_df.columns:
                    column_cfg["図書カードURL"] = st.column_config.LinkColumn(
                        "図書カードURL", display_text="図書カードを開く"
                    )
                st.dataframe(
                    display_df,
                    width="stretch",
                    hide_index=True,
                    height=540,
                    column_config=column_cfg,
                )

        with st.expander("🔧 実行されたDuckDB SQLクエリを確認", expanded=False):
            st.code(result.sql, language="sql")
            st.caption(f"バインドパラメータ: `{result.params}`")

    # ==========================================================
    # ④ フッター（コンプライアンス・クレジット表記：Rules 厳守）
    # ==========================================================
    st.divider()
    st.markdown(
        """
        <div style="font-size: 0.85rem; color: #57606a; line-height: 1.7;">
            <p style="margin-bottom: 0.4rem;"><strong>出典・ライセンス表記</strong></p>
            <p style="margin-bottom: 0.4rem;">
                本アプリケーションの本文データは、<a href="https://www.aozora.gr.jp/" target="_blank" rel="noopener noreferrer">青空文庫</a>の公開データ（著作権保護期間満了・著作権フラグ「なし」の作品のみ）に対し、検索・言語解析用の前処理（ルビ・注記の除去、形態素解析等）を行って構築した独自コーパスより配信しています。
            </p>
            <p style="margin-bottom: 0.4rem;">
                また、青空文庫の書誌情報（作品名・著者名・図書カードURL等）は、<a href="https://creativecommons.org/licenses/by/4.0/deed.ja" target="_blank" rel="noopener noreferrer">クリエイティブ・コモンズ 表示 4.0 国際（CC BY 4.0）</a> ライセンスに基づき、一部加工（検索用フォーマットへの変換等）の上で利用しています。各用例の底本情報・入力者および校正者クレジット等の詳細は、検索結果内の「作品名」または「図書カードURL」リンク先の青空文庫公式ページよりご確認いただけます。
            </p>
            <p style="margin-bottom: 0; color: #6e7781;">
                ※本サービスは個人による開発・運営であり、青空文庫の公式サービスや関与・公認を受けたものではありません。
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
