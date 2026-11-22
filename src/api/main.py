"""青空文庫「中納言風」短単位コーパス検索 FastAPI バックエンド。

起動方法:
    uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.search_engine import (
    BibliographicFilter,
    CollocationCondition,
    CorpusSearchEngine,
    SearchQuery,
    TokenCondition,
)

PROCESSED_DIR = Path(os.environ.get("AOZORA_PROCESSED_DIR", PROJECT_ROOT / "data" / "processed"))

DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]
extra_origins = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()
]

app = FastAPI(
    title="青空文庫「中納言風」短単位コーパス検索 API",
    description="Parquet + DuckDB による青空文庫パブリックドメイン作品向け短単位・共起検索API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys(DEFAULT_CORS_ORIGINS + extra_origins)),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def get_engine() -> CorpusSearchEngine:
    return CorpusSearchEngine(PROCESSED_DIR)


@lru_cache(maxsize=1)
def get_cached_stats() -> Dict[str, Any]:
    return get_engine().get_corpus_stats()


# ============================================================
# Pydantic リクエスト / レスポンススキーマ
# ============================================================
class TokenConditionSchema(BaseModel):
    lemma: str = ""
    surface: str = ""
    lemma_reading: str = ""
    pos: str = ""
    ctype: str = ""
    cform: str = ""
    goshu: str = ""
    match_mode: Literal["exact", "prefix", "contains", "regex"] = "exact"


class CollocationConditionSchema(BaseModel):
    direction: Literal["before", "after"] = "after"
    distance: int = Field(default=1, ge=1, le=10)
    distance_mode: Literal["exact", "within"] = "exact"
    condition: TokenConditionSchema = Field(default_factory=TokenConditionSchema)


class BibliographicFilterSchema(BaseModel):
    authors: List[str] = Field(default_factory=list)
    title_query: str = ""
    subcorpora: List[str] = Field(default_factory=list)
    ndc_prefix: str = ""
    published_year_min: Optional[int] = None
    published_year_max: Optional[int] = None


class SearchRequest(BaseModel):
    key: TokenConditionSchema
    collocations: List[CollocationConditionSchema] = Field(default_factory=list)
    bib: BibliographicFilterSchema = Field(default_factory=BibliographicFilterSchema)
    limit: int = Field(default=100, ge=1, le=5000)
    offset: int = Field(default=0, ge=0)
    context_chars: int = Field(default=30, ge=5, le=100)
    columns: Optional[List[str]] = None


class KwicRowSchema(BaseModel):
    book_id: int
    title: str
    author: str
    author_birth_year: Optional[int] = None
    published_year: Optional[int] = None
    ndc: str
    subcorpus: str
    card_url: str
    sentence_id: int
    text: str
    token_index: int
    start_pos: int
    end_pos: int
    surface: str
    lemma: str
    lemma_reading: str
    pos: str
    ctype: str
    cform: str
    goshu: str
    left_context: str
    left_context_full: str
    key_text: str
    right_context: str
    right_context_full: str


class SearchResponse(BaseModel):
    total_count: int
    returned_count: int
    elapsed_ms: float
    limit: int
    offset: int
    sql: str
    params: List[Any]
    items: List[KwicRowSchema]


class WorkItemSchema(BaseModel):
    book_id: int
    title: str
    author: str
    author_birth_year: Optional[int] = None
    published_year: Optional[int] = None
    ndc: str
    subcorpus: str
    card_url: str


class WorksListResponse(BaseModel):
    total_count: int
    returned_count: int
    limit: int
    offset: int
    q: str
    items: List[WorkItemSchema]


def _to_optional_int(val: Any) -> Optional[int]:
    if val is None or pd.isna(val):
        return None
    return int(val)


# ============================================================
# エンドポイント
# ============================================================
@app.get("/api/health")
def health_check() -> Dict[str, Any]:
    engine = get_engine()
    return {
        "status": "ok",
        "processed_dir": str(engine.processed_dir),
        "token_file_count": engine.token_file_count,
    }


@app.get("/api/stats")
def corpus_stats() -> Dict[str, Any]:
    """コーパス総統計と検索フォーム用マスタ候補を返す。"""
    try:
        return get_cached_stats()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/works", response_model=WorksListResponse)
def list_works(
    q: str = Query(default="", description="作品名または著者名の部分一致検索キーワード"),
    subcorpus: str = Query(default="", description="文字遣い種別フィルタ"),
    sort_by: Literal["book_id", "title", "author", "published_year"] = Query(default="book_id"),
    sort_order: Literal["asc", "desc"] = Query(default="asc"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> WorksListResponse:
    """books.parquet から収録作品一覧（ページネーション・検索対応）を返す。"""
    try:
        df, total_count = get_engine().list_works(
            q=q,
            subcorpus=subcorpus,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"作品一覧取得エラー: {exc}") from exc

    items: List[WorkItemSchema] = []
    if not df.empty:
        for row in df.to_dict(orient="records"):
            items.append(
                WorkItemSchema(
                    book_id=int(row["book_id"]),
                    title=str(row["title"]),
                    author=str(row["author"]),
                    author_birth_year=_to_optional_int(row.get("author_birth_year")),
                    published_year=_to_optional_int(row.get("published_year")),
                    ndc=str(row.get("ndc") or ""),
                    subcorpus=str(row.get("subcorpus") or ""),
                    card_url=str(row.get("card_url") or ""),
                )
            )

    return WorksListResponse(
        total_count=total_count,
        returned_count=len(items),
        limit=limit,
        offset=offset,
        q=q,
        items=items,
    )


@app.post("/api/search", response_model=SearchResponse)
def search_corpus(req: SearchRequest) -> SearchResponse:
    """短単位・共起KWIC検索を実行してJSONで返す。"""
    key_cond = TokenCondition(
        lemma=req.key.lemma,
        surface=req.key.surface,
        lemma_reading=req.key.lemma_reading,
        pos=req.key.pos,
        ctype=req.key.ctype,
        cform=req.key.cform,
        goshu=req.key.goshu,
        match_mode=req.key.match_mode,
    )
    if key_cond.is_empty():
        raise HTTPException(
            status_code=400,
            detail="キー（中心語）の検索条件を1つ以上指定してください。",
        )

    collocations = [
        CollocationCondition(
            direction=c.direction,
            distance=c.distance,
            distance_mode=c.distance_mode,
            condition=TokenCondition(
                lemma=c.condition.lemma,
                surface=c.condition.surface,
                lemma_reading=c.condition.lemma_reading,
                pos=c.condition.pos,
                ctype=c.condition.ctype,
                cform=c.condition.cform,
                goshu=c.condition.goshu,
                match_mode=c.condition.match_mode,
            ),
        )
        for c in req.collocations
    ]

    query = SearchQuery(
        key=key_cond,
        collocations=collocations,
        bib=BibliographicFilter(
            authors=req.bib.authors,
            title_query=req.bib.title_query,
            subcorpora=req.bib.subcorpora,
            ndc_prefix=req.bib.ndc_prefix,
            published_year_min=req.bib.published_year_min,
            published_year_max=req.bib.published_year_max,
        ),
        limit=req.limit,
        offset=req.offset,
    )

    try:
        result = get_engine().search(query, context_chars=req.context_chars)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"検索実行エラー: {exc}") from exc

    items: List[KwicRowSchema] = []
    if not result.df.empty:
        for row in result.df.to_dict(orient="records"):
            items.append(
                KwicRowSchema(
                    book_id=int(row["book_id"]),
                    title=str(row["title"]),
                    author=str(row["author"]),
                    author_birth_year=_to_optional_int(row.get("author_birth_year")),
                    published_year=_to_optional_int(row.get("published_year")),
                    ndc=str(row["ndc"] or ""),
                    subcorpus=str(row["subcorpus"] or ""),
                    card_url=str(row["card_url"] or ""),
                    sentence_id=int(row["sentence_id"]),
                    text=str(row["text"]),
                    token_index=int(row["token_index"]),
                    start_pos=int(row["start_pos"]),
                    end_pos=int(row["end_pos"]),
                    surface=str(row["surface"]),
                    lemma=str(row["lemma"]),
                    lemma_reading=str(row["lemma_reading"] or ""),
                    pos=str(row["pos"] or ""),
                    ctype=str(row["ctype"] or ""),
                    cform=str(row["cform"] or ""),
                    goshu=str(row["goshu"] or ""),
                    left_context=str(row["left_context"]),
                    left_context_full=str(row["left_context_full"]),
                    key_text=str(row["key_text"]),
                    right_context=str(row["right_context"]),
                    right_context_full=str(row["right_context_full"]),
                )
            )

    return SearchResponse(
        total_count=result.total_count,
        returned_count=len(items),
        elapsed_ms=round(result.elapsed_ms, 1),
        limit=req.limit,
        offset=req.offset,
        sql=result.sql,
        params=result.params,
        items=items,
    )
