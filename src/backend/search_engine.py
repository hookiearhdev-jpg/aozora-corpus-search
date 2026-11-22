"""DuckDB + Parquet による中納言風短単位・共起検索エンジン。

Parquetスキーマ（GEMINI.md 準拠）:
- books.parquet    : book_id, title, author, author_birth_year, published_year, ndc, card_url, subcorpus
- sentences.parquet: sentence_id, book_id, text
- tokens.parquet   : sentence_id, token_index, start_pos, end_pos, surface, lemma, lemma_reading, pos, ctype, cform, goshu
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import duckdb
import pandas as pd

MatchMode = Literal["exact", "prefix", "contains", "regex"]
Direction = Literal["before", "after"]
DistanceMode = Literal["exact", "within"]


@dataclass
class TokenCondition:
    """1語（キーまたは共起語）に対する短単位検索条件（入力項目はすべてAND結合）。"""

    lemma: str = ""
    surface: str = ""
    lemma_reading: str = ""
    pos: str = ""
    ctype: str = ""
    cform: str = ""
    goshu: str = ""
    match_mode: MatchMode = "exact"

    def is_empty(self) -> bool:
        return not any(
            v.strip()
            for v in (
                self.lemma,
                self.surface,
                self.lemma_reading,
                self.pos,
                self.ctype,
                self.cform,
                self.goshu,
            )
        )


@dataclass
class CollocationCondition:
    """キーに対する前方/後方共起条件。"""

    direction: Direction = "after"
    distance: int = 1
    distance_mode: DistanceMode = "exact"
    condition: TokenCondition = field(default_factory=TokenCondition)


@dataclass
class BibliographicFilter:
    """書誌メタデータによる絞り込み条件（任意）。"""

    authors: List[str] = field(default_factory=list)
    title_query: str = ""
    subcorpora: List[str] = field(default_factory=list)
    ndc_prefix: str = ""
    published_year_min: Optional[int] = None
    published_year_max: Optional[int] = None


@dataclass
class SearchQuery:
    """短単位KWIC検索クエリ全体。"""

    key: TokenCondition
    collocations: List[CollocationCondition] = field(default_factory=list)
    bib: BibliographicFilter = field(default_factory=BibliographicFilter)
    limit: int = 1000
    offset: int = 0


@dataclass
class SearchResult:
    """検索実行結果。"""

    df: pd.DataFrame
    total_count: int
    elapsed_ms: float
    sql: str
    params: List[Any]


def _escape_like(value: str) -> str:
    """SQLのLIKEパターン用に特殊文字をエスケープする。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _append_text_condition(
    clauses: List[str],
    params: List[Any],
    col_expr: str,
    value: str,
    match_mode: MatchMode,
) -> None:
    """語彙素・表層形・読みに対する一致条件をSQL句に追加する。"""
    v = value.strip()
    if not v:
        return
    if match_mode == "exact":
        clauses.append(f"{col_expr} = ?")
        params.append(v)
    elif match_mode == "prefix":
        clauses.append(f"{col_expr} LIKE ? ESCAPE '\\'")
        params.append(f"{_escape_like(v)}%")
    elif match_mode == "contains":
        clauses.append(f"{col_expr} LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(v)}%")
    elif match_mode == "regex":
        clauses.append(f"regexp_matches({col_expr}, ?)")
        params.append(v)
    else:
        raise ValueError(f"未対応の match_mode です: {match_mode}")


def _append_hierarchy_condition(
    clauses: List[str],
    params: List[Any],
    col_expr: str,
    value: str,
) -> None:
    """UniDicの階層タグ（pos / ctype / cform）に対する中納言準拠の階層一致条件を追加する。

    例:
      - '助詞'     -> '助詞' または '助詞-%' にマッチ
      - '動詞-一般' -> '動詞-一般' または '動詞-一般-%' にマッチ
      - '連用形'   -> '連用形' または '連用形-%' にマッチ
    """
    v = value.strip()
    if not v:
        return
    clauses.append(f"({col_expr} = ? OR {col_expr} LIKE ? ESCAPE '\\')")
    params.append(v)
    params.append(f"{_escape_like(v)}-%")


def _build_token_where_clauses(
    alias: str,
    cond: TokenCondition,
) -> Tuple[List[str], List[Any]]:
    """単一トークンエイリアスに対するWHERE句とパラメータを構築する。"""
    clauses: List[str] = []
    params: List[Any] = []

    _append_text_condition(clauses, params, f"{alias}.lemma", cond.lemma, cond.match_mode)
    _append_text_condition(clauses, params, f"{alias}.surface", cond.surface, cond.match_mode)
    _append_text_condition(
        clauses, params, f"{alias}.lemma_reading", cond.lemma_reading, cond.match_mode
    )
    _append_hierarchy_condition(clauses, params, f"{alias}.pos", cond.pos)
    _append_hierarchy_condition(clauses, params, f"{alias}.ctype", cond.ctype)
    _append_hierarchy_condition(clauses, params, f"{alias}.cform", cond.cform)

    if cond.goshu.strip():
        clauses.append(f"{alias}.goshu = ?")
        params.append(cond.goshu.strip())

    return clauses, params


def extract_kwic_columns(
    df: pd.DataFrame,
    context_chars: int = 30,
) -> pd.DataFrame:
    """検索結果DataFrameに KWIC（前文脈・キー・後文脈）列を正確に切り出して付与する。"""
    result = df.copy()
    if result.empty:
        result["left_context_full"] = pd.Series(dtype="object")
        result["key_text"] = pd.Series(dtype="object")
        result["right_context_full"] = pd.Series(dtype="object")
        result["left_context"] = pd.Series(dtype="object")
        result["right_context"] = pd.Series(dtype="object")
        return result

    left_full: List[str] = []
    key_list: List[str] = []
    right_full: List[str] = []
    left_short: List[str] = []
    right_short: List[str] = []

    for text, start_pos, end_pos in zip(
        result["text"].tolist(),
        result["start_pos"].tolist(),
        result["end_pos"].tolist(),
    ):
        s = int(start_pos)
        e = int(end_pos)
        l_text = text[:s]
        k_text = text[s:e]
        r_text = text[e:]

        left_full.append(l_text)
        key_list.append(k_text)
        right_full.append(r_text)

        if context_chars > 0 and len(l_text) > context_chars:
            left_short.append("…" + l_text[-context_chars:])
        else:
            left_short.append(l_text)

        if context_chars > 0 and len(r_text) > context_chars:
            right_short.append(r_text[:context_chars] + "…")
        else:
            right_short.append(r_text)

    result["left_context_full"] = left_full
    result["key_text"] = key_list
    result["right_context_full"] = right_full
    result["left_context"] = left_short
    result["right_context"] = right_short
    return result


class CorpusSearchEngine:
    """Parquet + DuckDB を用いた短単位コーパス検索エンジン。"""

    def __init__(self, processed_dir: Path | str = Path("data/processed")) -> None:
        self.processed_dir = Path(processed_dir).resolve()
        self.books_path = self.processed_dir / "books.parquet"
        self.sentences_path = self.processed_dir / "sentences.parquet"

        for p in (self.books_path, self.sentences_path):
            if not p.exists():
                raise FileNotFoundError(f"必要なParquetファイルが見つかりません: {p}")

        shard_files = sorted(self.processed_dir.glob("tokens_*.parquet"))
        single_token_file = self.processed_dir / "tokens.parquet"
        if shard_files:
            self.tokens_path = self.processed_dir / "tokens_*.parquet"
            self.token_file_count = len(shard_files)
        elif single_token_file.exists():
            self.tokens_path = single_token_file
            self.token_file_count = 1
        else:
            raise FileNotFoundError(
                f"トークンParquetファイルが見つかりません: {single_token_file} または tokens_*.parquet"
            )

    def _parquet_sql_path(self, path: Path) -> str:
        # DuckDB read_parquet 用に POSIX パスへ変換し、シングルクォートをエスケープ
        return path.as_posix().replace("'", "''")

    def get_corpus_stats(self) -> Dict[str, Any]:
        """コーパス全体の統計情報とUIフィルタ用マスタ候補を取得する。"""
        books_p = self._parquet_sql_path(self.books_path)
        sents_p = self._parquet_sql_path(self.sentences_path)
        tokens_p = self._parquet_sql_path(self.tokens_path)

        with duckdb.connect(database=":memory:") as con:
            book_count, author_count, min_pub, max_pub = con.execute(
                f"""
                SELECT
                    COUNT(*),
                    COUNT(DISTINCT author),
                    MIN(published_year),
                    MAX(published_year)
                FROM read_parquet('{books_p}')
                """
            ).fetchone()
            sentence_count = con.execute(
                f"SELECT COUNT(*) FROM read_parquet('{sents_p}')"
            ).fetchone()[0]
            token_count = con.execute(
                f"SELECT COUNT(*) FROM read_parquet('{tokens_p}')"
            ).fetchone()[0]

            authors = [
                r[0]
                for r in con.execute(
                    f"SELECT DISTINCT author FROM read_parquet('{books_p}') ORDER BY author"
                ).fetchall()
            ]
            subcorpora = [
                r[0]
                for r in con.execute(
                    f"SELECT DISTINCT subcorpus FROM read_parquet('{books_p}') WHERE subcorpus != '' ORDER BY subcorpus"
                ).fetchall()
            ]
            raw_pos = [
                r[0]
                for r in con.execute(
                    f"SELECT pos FROM read_parquet('{tokens_p}') WHERE pos != '' GROUP BY pos ORDER BY COUNT(*) DESC"
                ).fetchall()
            ]
            # 中納言の階層検索用に大分類・中分類プレフィックスも候補に含める
            pos_prefixes: List[str] = []
            seen_pos = set()
            for p in raw_pos:
                parts = p.split("-")
                for depth in range(1, len(parts) + 1):
                    cand = "-".join(parts[:depth])
                    if cand not in seen_pos:
                        seen_pos.add(cand)
                        pos_prefixes.append(cand)
            pos_options = sorted(pos_prefixes)

            raw_ctype = [
                r[0]
                for r in con.execute(
                    f"SELECT DISTINCT ctype FROM read_parquet('{tokens_p}') WHERE ctype != '' ORDER BY ctype"
                ).fetchall()
            ]
            ctype_set = set()
            for ct in raw_ctype:
                ctype_set.add(ct)
                ctype_set.add(ct.split("-")[0])
            ctype_options = sorted(ctype_set)

            raw_cform = [
                r[0]
                for r in con.execute(
                    f"SELECT DISTINCT cform FROM read_parquet('{tokens_p}') WHERE cform != '' ORDER BY cform"
                ).fetchall()
            ]
            cform_set = set()
            for cf in raw_cform:
                cform_set.add(cf)
                cform_set.add(cf.split("-")[0])
            cform_options = sorted(cform_set)

            goshu_options = [
                r[0]
                for r in con.execute(
                    f"SELECT goshu FROM read_parquet('{tokens_p}') WHERE goshu != '' GROUP BY goshu ORDER BY COUNT(*) DESC"
                ).fetchall()
            ]

        return {
            "book_count": int(book_count),
            "author_count": int(author_count),
            "sentence_count": int(sentence_count),
            "token_count": int(token_count),
            "min_published_year": int(min_pub) if min_pub is not None else None,
            "max_published_year": int(max_pub) if max_pub is not None else None,
            "authors": authors,
            "subcorpora": subcorpora,
            "pos_options": pos_options,
            "ctype_options": ctype_options,
            "cform_options": cform_options,
            "goshu_options": goshu_options,
        }

    def build_sql(self, query: SearchQuery) -> Tuple[str, List[Any]]:
        """検索条件から1回のクエリで総件数(_total_count)とKWIC結果を取得する最適化SQLを構築する。

        1.5億トークン規模での高速化設計:
        - CTE `key_hits` でキー(t1)の該当行を先に絞り込み、共起テーブル(t2, t3...)を
          streaming probe 側として結合することで巨大ハッシュテーブル構築を回避。
        - `COUNT(*) OVER ()` により、Parquetの2回スキャンを廃して1クエリで総件数と上位LIMIT件を取得。
        """
        if query.key.is_empty():
            raise ValueError("キー（中心語）の検索条件を1つ以上指定してください。")

        books_p = self._parquet_sql_path(self.books_path)
        sents_p = self._parquet_sql_path(self.sentences_path)
        tokens_p = self._parquet_sql_path(self.tokens_path)

        params: List[Any] = []
        cte_parts: List[str] = []

        # 1. キー（中心語 t1）抽出CTE
        key_clauses, key_params = _build_token_where_clauses("t1", query.key)
        params.extend(key_params)
        cte_parts.append(
            "key_hits AS MATERIALIZED (\n"
            "    SELECT\n"
            "        t1.sentence_id,\n"
            "        t1.token_index,\n"
            "        t1.start_pos,\n"
            "        t1.end_pos,\n"
            "        t1.surface,\n"
            "        t1.lemma,\n"
            "        t1.lemma_reading,\n"
            "        t1.pos,\n"
            "        t1.ctype,\n"
            "        t1.cform,\n"
            "        t1.goshu\n"
            f"    FROM read_parquet('{tokens_p}') AS t1\n"
            "    WHERE "
            + "\n      AND ".join(key_clauses)
            + "\n)"
        )

        # 2. 共起条件（tokens.parquet の自己結合 t2, t3, ... を段階的に適用）
        current_cte = "key_hits"
        active_collocations = [c for c in query.collocations if not c.condition.is_empty()]
        for idx, colloc in enumerate(active_collocations, start=2):
            alias = f"t{idx}"
            next_cte = f"colloc_{idx}"
            dist = int(colloc.distance)
            if not (1 <= dist <= 10):
                raise ValueError(f"共起距離は 1〜10 の範囲で指定してください: {dist}")

            if colloc.distance_mode == "exact":
                offset = -dist if colloc.direction == "before" else dist
                sign = "-" if offset < 0 else "+"
                join_cond = (
                    f"{alias}.sentence_id = prev.sentence_id "
                    f"AND {alias}.token_index = prev.token_index {sign} {abs(offset)}"
                )
                distinct_kw = ""
            elif colloc.distance_mode == "within":
                if colloc.direction == "before":
                    join_cond = (
                        f"{alias}.sentence_id = prev.sentence_id "
                        f"AND {alias}.token_index BETWEEN prev.token_index - {dist} AND prev.token_index - 1"
                    )
                else:
                    join_cond = (
                        f"{alias}.sentence_id = prev.sentence_id "
                        f"AND {alias}.token_index BETWEEN prev.token_index + 1 AND prev.token_index + {dist}"
                    )
                distinct_kw = "DISTINCT "
            else:
                raise ValueError(f"未対応の distance_mode です: {colloc.distance_mode}")

            c_clauses, c_params = _build_token_where_clauses(alias, colloc.condition)
            params.extend(c_params)

            # 大きい tokens (tN) を左辺(probe)、絞られた prev を右辺(build)に配置してハッシュ結合を高速化
            cte_parts.append(
                f"{next_cte} AS (\n"
                f"    SELECT {distinct_kw}prev.*\n"
                f"    FROM read_parquet('{tokens_p}') AS {alias}\n"
                f"    JOIN {current_cte} AS prev ON {join_cond}\n"
                "    WHERE "
                + "\n      AND ".join(c_clauses)
                + "\n)"
            )
            current_cte = next_cte

        # 3. 書誌絞り込み条件
        bib = query.bib
        bib_where: List[str] = []
        if bib.authors:
            placeholders = ", ".join(["?"] * len(bib.authors))
            bib_where.append(f"b.author IN ({placeholders})")
            params.extend(bib.authors)
        if bib.title_query.strip():
            bib_where.append("b.title LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(bib.title_query.strip())}%")
        if bib.subcorpora:
            placeholders = ", ".join(["?"] * len(bib.subcorpora))
            bib_where.append(f"b.subcorpus IN ({placeholders})")
            params.extend(bib.subcorpora)
        if bib.ndc_prefix.strip():
            bib_where.append("b.ndc LIKE ? ESCAPE '\\'")
            params.append(f"{_escape_like(bib.ndc_prefix.strip())}%")
        if bib.published_year_min is not None:
            bib_where.append("b.published_year >= ?")
            params.append(int(bib.published_year_min))
        if bib.published_year_max is not None:
            bib_where.append("b.published_year <= ?")
            params.append(int(bib.published_year_max))

        bib_where_sql = ("\nWHERE " + "\n  AND ".join(bib_where)) if bib_where else ""

        select_sql = (
            "WITH\n"
            + ",\n".join(cte_parts)
            + "\nSELECT\n"
            "    COUNT(*) OVER () AS _total_count,\n"
            "    b.book_id,\n"
            "    b.title,\n"
            "    b.author,\n"
            "    b.author_birth_year,\n"
            "    b.published_year,\n"
            "    b.ndc,\n"
            "    b.subcorpus,\n"
            "    b.card_url,\n"
            "    s.sentence_id,\n"
            "    s.text,\n"
            "    m.token_index,\n"
            "    m.start_pos,\n"
            "    m.end_pos,\n"
            "    m.surface,\n"
            "    m.lemma,\n"
            "    m.lemma_reading,\n"
            "    m.pos,\n"
            "    m.ctype,\n"
            "    m.cform,\n"
            "    m.goshu\n"
            f"FROM {current_cte} AS m\n"
            f"JOIN read_parquet('{sents_p}') AS s ON m.sentence_id = s.sentence_id\n"
            f"JOIN read_parquet('{books_p}') AS b ON s.book_id = b.book_id"
            f"{bib_where_sql}\n"
            "ORDER BY b.book_id, s.sentence_id, m.token_index\n"
            f"LIMIT {int(query.limit)} OFFSET {int(query.offset)}"
        )

        return select_sql, params

    def search(self, query: SearchQuery, context_chars: int = 30) -> SearchResult:
        """動的SQLをDuckDBで実行し、KWIC整形済みDataFrameと統計を返す。"""
        select_sql, params = self.build_sql(query)
        t0 = time.perf_counter()
        with duckdb.connect(database=":memory:") as con:
            con.execute("SET preserve_insertion_order = false")
            raw_df = con.execute(select_sql, params).fetchdf()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        if raw_df.empty:
            total_count = 0
        else:
            total_count = int(raw_df["_total_count"].iloc[0])
        if "_total_count" in raw_df.columns:
            raw_df = raw_df.drop(columns=["_total_count"])

        kwic_df = extract_kwic_columns(raw_df, context_chars=context_chars)
        return SearchResult(
            df=kwic_df,
            total_count=total_count,
            elapsed_ms=elapsed_ms,
            sql=select_sql,
            params=params,
        )

    def list_works(
        self,
        q: str = "",
        subcorpus: str = "",
        sort_by: Literal["book_id", "title", "author", "published_year"] = "book_id",
        sort_order: Literal["asc", "desc"] = "asc",
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[pd.DataFrame, int]:
        """books.parquet を DuckDB でクエリし、検索・ページネーション付きの収録作品一覧を返す。"""
        books_p = self._parquet_sql_path(self.books_path)
        where_clauses: List[str] = []
        params: List[Any] = []

        q_trimmed = q.strip()
        if q_trimmed:
            pattern = f"%{_escape_like(q_trimmed)}%"
            where_clauses.append("(title LIKE ? ESCAPE '\\' OR author LIKE ? ESCAPE '\\')")
            params.extend([pattern, pattern])

        sub_trimmed = subcorpus.strip()
        if sub_trimmed:
            where_clauses.append("subcorpus = ?")
            params.append(sub_trimmed)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        allowed_sort = {
            "book_id": "book_id",
            "title": "title",
            "author": "author",
            "published_year": "published_year",
        }
        sort_col = allowed_sort.get(sort_by, "book_id")
        order_dir = "DESC" if sort_order.lower() == "desc" else "ASC"
        nulls_clause = " NULLS LAST" if sort_col == "published_year" else ""

        with duckdb.connect(database=":memory:") as con:
            total_count = int(
                con.execute(
                    f"SELECT COUNT(*) FROM read_parquet('{books_p}') {where_sql}",
                    params,
                ).fetchone()[0]
            )
            df = con.execute(
                f"""
                SELECT
                    book_id,
                    title,
                    author,
                    author_birth_year,
                    published_year,
                    ndc,
                    subcorpus,
                    card_url
                FROM read_parquet('{books_p}')
                {where_sql}
                ORDER BY {sort_col} {order_dir}{nulls_clause}, book_id ASC
                LIMIT {int(limit)} OFFSET {int(offset)}
                """,
                params,
            ).fetchdf()

        return df, total_count
