import type {
  CorpusStats,
  SearchRequest,
  SearchResponse,
  SortOrder,
  WorksListResponse,
  WorksSortBy,
} from "../types/corpus";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

export async function fetchCorpusStats(): Promise<CorpusStats> {
  const res = await fetch(`${API_BASE_URL}/api/stats`, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`統計情報の取得に失敗しました (${res.status}): ${text}`);
  }
  return (await res.json()) as CorpusStats;
}

export interface FetchWorksParams {
  q?: string;
  subcorpus?: string;
  sort_by?: WorksSortBy;
  sort_order?: SortOrder;
  limit?: number;
  offset?: number;
}

export async function fetchWorks(
  params: FetchWorksParams = {}
): Promise<WorksListResponse> {
  const qs = new URLSearchParams();
  if (params.q !== undefined && params.q !== "") qs.set("q", params.q);
  if (params.subcorpus) qs.set("subcorpus", params.subcorpus);
  if (params.sort_by) qs.set("sort_by", params.sort_by);
  if (params.sort_order) qs.set("sort_order", params.sort_order);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));

  const queryStr = qs.toString();
  const res = await fetch(
    `${API_BASE_URL}/api/works${queryStr ? `?${queryStr}` : ""}`,
    {
      method: "GET",
      headers: { Accept: "application/json" },
    }
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`収録作品一覧の取得に失敗しました (${res.status}): ${text}`);
  }
  return (await res.json()) as WorksListResponse;
}

export async function searchCorpus(payload: SearchRequest): Promise<SearchResponse> {
  const res = await fetch(`${API_BASE_URL}/api/search`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let detail = `検索に失敗しました (${res.status})`;
    try {
      const errJson = (await res.json()) as { detail?: string };
      if (errJson.detail) detail = errJson.detail;
    } catch {
      // ignore json parse error
    }
    throw new Error(detail);
  }
  return (await res.json()) as SearchResponse;
}
