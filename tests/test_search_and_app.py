"""Step 2 検証テスト: DuckDB検索エンジン & Streamlit UI (AppTest) の包括検証。"""

from __future__ import annotations

import io
from pathlib import Path

import duckdb
import pandas as pd
from streamlit.testing.v1 import AppTest

from src.backend.search_engine import (
    CollocationCondition,
    CorpusSearchEngine,
    SearchQuery,
    TokenCondition,
)

PROCESSED_DIR = Path("data/processed")
TOKENS_PARQUET = (
    (PROCESSED_DIR / "tokens_*.parquet").resolve().as_posix()
    if list(PROCESSED_DIR.glob("tokens_*.parquet"))
    else (PROCESSED_DIR / "tokens.parquet").resolve().as_posix()
)


def assert_kwic_alignment(df: pd.DataFrame, label: str) -> None:
    """全行で KWIC（前文脈 + キー + 後文脈 == 文全文、かつ キー == surface）を厳密検証する。"""
    assert not df.empty, f"[{label}] 検索結果が0件です。"
    for row in df.itertuples(index=False):
        reconstructed = row.left_context_full + row.key_text + row.right_context_full
        assert reconstructed == row.text, (
            f"[{label}] KWIC再構成が元文と不一致:\n"
            f"  reconstructed={reconstructed!r}\n"
            f"  original     ={row.text!r}"
        )
        assert row.key_text == row.surface, (
            f"[{label}] 切り出しキーが surface と不一致: key={row.key_text!r}, surface={row.surface!r}"
        )
        assert row.card_url and row.card_url.startswith("https://www.aozora.gr.jp/"), (
            f"[{label}] 図書カードURLが不正: {row.card_url!r}"
        )


def test_backend_single_key_search() -> None:
    print("=== 1. 単一キー検索テスト（語彙素 & 品詞+活用形AND） ===")
    engine = CorpusSearchEngine(PROCESSED_DIR)

    # 1-A. 語彙素「走る」
    res_lemma = engine.search(SearchQuery(key=TokenCondition(lemma="走る"), limit=200))
    assert res_lemma.total_count > 0
    assert (res_lemma.df["lemma"] == "走る").all()
    assert_kwic_alignment(res_lemma.df, "単一キー:語彙素=走る")
    print(
        f"  [OK] 語彙素='走る': 総ヒット {res_lemma.total_count:,} 件 ({res_lemma.elapsed_ms:.1f} ms) / KWIC全件一致"
    )

    # 1-B. 品詞=動詞-一般 AND 活用形=連用形（階層一致）
    res_pos_cform = engine.search(
        SearchQuery(key=TokenCondition(pos="動詞-一般", cform="連用形"), limit=200)
    )
    assert res_pos_cform.total_count > 0
    assert (res_pos_cform.df["pos"] == "動詞-一般").all()
    assert res_pos_cform.df["cform"].str.startswith("連用形").all()
    assert_kwic_alignment(res_pos_cform.df, "単一キー:動詞-一般&連用形")
    print(
        f"  [OK] 品詞='動詞-一般' AND 活用形='連用形': 総ヒット {res_pos_cform.total_count:,} 件 "
        f"({res_pos_cform.elapsed_ms:.1f} ms) / KWIC全件一致"
    )


def test_backend_collocation_search() -> None:
    print("\n=== 2. 共起検索テスト（2語前=助詞 / 直後=て / 前後同時共起 / 範囲共起） ===")
    engine = CorpusSearchEngine(PROCESSED_DIR)

    # 2-A. 2語前が「品詞=助詞」 + キーが語彙素「心」
    q_before2 = SearchQuery(
        key=TokenCondition(lemma="心"),
        collocations=[
            CollocationCondition(
                direction="before",
                distance=2,
                distance_mode="exact",
                condition=TokenCondition(pos="助詞"),
            )
        ],
        limit=100,
    )
    res_b2 = engine.search(q_before2)
    assert res_b2.total_count > 0
    assert_kwic_alignment(res_b2.df, "前方2語共起:助詞+心")

    # 実際に全ヒットの token_index - 2 が助詞であることを DuckDB でクロス検証
    con = duckdb.connect()
    pairs = list(zip(res_b2.df["sentence_id"].tolist(), res_b2.df["token_index"].tolist()))
    for sid, tidx in pairs[:30]:
        colloc_pos = con.execute(
            f"SELECT pos FROM read_parquet('{TOKENS_PARQUET}') WHERE sentence_id = ? AND token_index = ?",
            [int(sid), int(tidx) - 2],
        ).fetchone()
        assert colloc_pos is not None and colloc_pos[0].startswith("助詞"), (
            f"2語前トークンが助詞ではありません: sid={sid}, tidx={tidx}, pos={colloc_pos}"
        )
    con.close()
    print(
        f"  [OK] 2語前(品詞='助詞') + キー(語彙素='心'): 総ヒット {res_b2.total_count:,} 件 "
        f"({res_b2.elapsed_ms:.1f} ms) / token_index-2 実データ照合OK"
    )
    sample = res_b2.df.iloc[0]
    print(
        f"       例: [{sample['title']} / {sample['author']}] "
        f"{sample['left_context']} 【{sample['key_text']}】 {sample['right_context']}"
    )

    # 2-B. 前方共起（直前1語: 格助詞「を」）AND 後方共起（直後1語: 助詞「て」）+ キー（動詞-一般・連用形）
    q_both = SearchQuery(
        key=TokenCondition(pos="動詞-一般", cform="連用形"),
        collocations=[
            CollocationCondition(
                direction="before",
                distance=1,
                distance_mode="exact",
                condition=TokenCondition(lemma="を", pos="助詞-格助詞"),
            ),
            CollocationCondition(
                direction="after",
                distance=1,
                distance_mode="exact",
                condition=TokenCondition(lemma="て", pos="助詞"),
            ),
        ],
        limit=100,
    )
    res_both = engine.search(q_both)
    assert res_both.total_count > 0
    assert_kwic_alignment(res_both.df, "前後同時共起")
    print(
        f"  [OK] 前後同時共起（直前「を」+ 動詞-一般・連用形 + 直後「て」）: "
        f"総ヒット {res_both.total_count:,} 件 ({res_both.elapsed_ms:.1f} ms)"
    )

    # 2-C. 範囲共起（1〜3語以内に語彙素「ない」）＋ 重複ヒット排除の確認
    q_within = SearchQuery(
        key=TokenCondition(pos="動詞-一般"),
        collocations=[
            CollocationCondition(
                direction="after",
                distance=3,
                distance_mode="within",
                condition=TokenCondition(lemma="ない"),
            )
        ],
        limit=100,
    )
    res_within = engine.search(q_within)
    assert res_within.total_count > 0
    # 同一 (sentence_id, token_index) の重複がないこと
    dup_cnt = res_within.df.duplicated(subset=["sentence_id", "token_index"]).sum()
    assert dup_cnt == 0, f"範囲共起で重複行が発生しました: {dup_cnt}"
    assert_kwic_alignment(res_within.df, "範囲共起:1〜3語以内")
    print(
        f"  [OK] 範囲共起（動詞-一般 + 後方1〜3語以内「ない」）: "
        f"総ヒット {res_within.total_count:,} 件 ({res_within.elapsed_ms:.1f} ms) / 重複0件"
    )

    # 2-D. CSV（UTF-8 BOM付き）出力検証
    csv_bytes = res_b2.df[
        ["title", "author", "left_context", "key_text", "right_context", "lemma", "pos", "cform", "card_url"]
    ].to_csv(index=False).encode("utf-8-sig")
    assert csv_bytes.startswith(b"\xef\xbb\xbf"), "CSVにUTF-8 BOMが付与されていません。"
    parsed_csv = pd.read_csv(io.BytesIO(csv_bytes), encoding="utf-8-sig")
    assert len(parsed_csv) == len(res_b2.df)
    assert "card_url" in parsed_csv.columns
    print(f"  [OK] UTF-8 BOM付きCSV生成確認: {len(csv_bytes):,} bytes / {len(parsed_csv)} 行")


def test_streamlit_app_ui() -> None:
    print("\n=== 3. Streamlit UI (AppTest) 統合テスト ===")
    app_path = Path(__file__).resolve().parents[1] / "src" / "frontend" / "app.py"
    at = AppTest.from_file(str(app_path), default_timeout=30)
    at.run()
    assert not at.exception, f"初期起動で例外が発生: {at.exception}"

    # フッターのクレジット表記（CC BY 4.0 / 青空文庫）を検証
    all_markdown = "\n".join(m.value for m in at.markdown)
    assert "CC BY 4.0" in all_markdown and "青空文庫" in all_markdown, (
        "フッターに青空文庫 (CC BY 4.0) のクレジット表記が見つかりません。"
    )
    print("  [OK] 初期起動＆フッターの青空文庫 (CC BY 4.0) クレジット表記を確認")

    # 3-A. 単一キー検索（語彙素='走る'）
    at.text_input(key="key_lemma").set_value("走る")
    search_btn = [b for b in at.button if "検索を実行" in b.label][0]
    search_btn.click().run()
    assert not at.exception, f"単一キー検索で例外が発生: {at.exception}"
    assert at.session_state["last_result"] is not None
    assert at.session_state["last_result"].total_count > 0
    assert len(at.dataframe) == 1, "st.dataframe が描画されていません。"
    print(
        f"  [OK] UI単一キー検索（語彙素='走る'）: "
        f"{at.session_state['last_result'].total_count:,} 件ヒット / st.dataframe & KWIC描画OK"
    )

    # 3-B. 動的に「＋ 前方共起を追加」して 2語前=助詞 + キー=心 を実行
    at.text_input(key="key_lemma").set_value("心")
    add_before_btn = [b for b in at.button if "前方共起を追加" in b.label][0]
    add_before_btn.click().run()
    assert not at.exception
    assert len(at.session_state["colloc_items"]) == 1
    cid = at.session_state["colloc_items"][0]["id"]

    # 距離モードを「ちょうど N 語」に変更して N=2、品詞=助詞 を設定
    at.selectbox(key=f"colloc_dist_mode_{cid}").set_value("ちょうど N 語").run()
    assert not at.exception
    at.number_input(key=f"colloc_dist_{cid}").set_value(2)
    at.selectbox(key=f"colloc_pos_{cid}").set_value("助詞")
    search_btn = [b for b in at.button if "検索を実行" in b.label][0]
    search_btn.click().run()
    assert not at.exception, f"共起検索UI実行で例外が発生: {at.exception}"
    ui_res = at.session_state["last_result"]
    assert ui_res.total_count > 0
    assert_kwic_alignment(ui_res.df, "UI共起検索:2語前助詞+心")
    print(
        f"  [OK] UI動的共起追加＆検索（2語前=助詞 + キー=心）: "
        f"{ui_res.total_count:,} 件ヒット / KWIC位置ズレ0件"
    )

    # 3-C. st.multiselect による表示列切り替え検証（図書カードURL・語種を追加）
    col_ms = [m for m in at.multiselect if "表示する列を選択" in m.label][0]
    new_cols = ["作品名", "著者", "前文脈", "キー", "後文脈", "語種", "図書カードURL"]
    col_ms.set_value(new_cols).run()
    assert not at.exception
    rendered_df = at.dataframe[0].value
    assert list(rendered_df.columns) == new_cols, f"表示列が一致しません: {list(rendered_df.columns)}"
    print(f"  [OK] st.multiselect 表示列切り替え確認: {list(rendered_df.columns)}")

    # 3-D. プリセットボタン動作検証（動詞-一般・連用形 + 直後「て」）
    preset_btn = [b for b in at.button if "動詞-一般(連用形)" in b.label][0]
    preset_btn.click().run()
    assert not at.exception
    search_btn = [b for b in at.button if "検索を実行" in b.label][0]
    search_btn.click().run()
    assert not at.exception
    assert at.session_state["last_result"].total_count > 0
    print(
        f"  [OK] プリセット検索（動詞-一般・連用形 + 直後「て」）: "
        f"{at.session_state['last_result'].total_count:,} 件ヒット"
    )


if __name__ == "__main__":
    test_backend_single_key_search()
    test_backend_collocation_search()
    test_streamlit_app_ui()
    print("\nALL STEP 2 TESTS PASSED SUCCESSFULLY!")
