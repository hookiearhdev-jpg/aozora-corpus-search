export type MatchMode = "exact" | "prefix" | "contains" | "regex";
export type Direction = "before" | "after";
export type DistanceMode = "exact" | "within";

export interface TokenCondition {
  lemma: string;
  surface: string;
  lemma_reading: string;
  pos: string;
  ctype: string;
  cform: string;
  goshu: string;
  match_mode: MatchMode;
}

export interface CollocationItem {
  id: number;
  direction: Direction;
  distanceType: "adjacent" | "exact" | "within";
  distance: number;
  showAdvanced: boolean;
  condition: TokenCondition;
}

export interface CollocationRequest {
  direction: Direction;
  distance: number;
  distance_mode: DistanceMode;
  condition: TokenCondition;
}

export interface BibliographicFilter {
  authors: string[];
  title_query: string;
  subcorpora: string[];
  ndc_prefix: string;
  published_year_min: number | null;
  published_year_max: number | null;
}

export interface SearchRequest {
  key: TokenCondition;
  collocations: CollocationRequest[];
  bib: BibliographicFilter;
  limit: number;
  offset: number;
  context_chars: number;
  columns?: string[];
}

export interface KwicRow {
  book_id: number;
  title: string;
  author: string;
  author_birth_year: number | null;
  published_year: number | null;
  ndc: string;
  subcorpus: string;
  card_url: string;
  sentence_id: number;
  text: string;
  token_index: number;
  start_pos: number;
  end_pos: number;
  surface: string;
  lemma: string;
  lemma_reading: string;
  pos: string;
  ctype: string;
  cform: string;
  goshu: string;
  left_context: string;
  left_context_full: string;
  key_text: string;
  right_context: string;
  right_context_full: string;
}

export interface SearchResponse {
  total_count: number;
  returned_count: number;
  elapsed_ms: number;
  limit: number;
  offset: number;
  sql: string;
  params: unknown[];
  items: KwicRow[];
}

export interface CorpusStats {
  book_count: number;
  author_count: number;
  sentence_count: number;
  token_count: number;
  min_published_year: number | null;
  max_published_year: number | null;
  authors: string[];
  subcorpora: string[];
  pos_options: string[];
  ctype_options: string[];
  cform_options: string[];
  goshu_options: string[];
}

export type WorksSortBy = "book_id" | "title" | "author" | "published_year";
export type SortOrder = "asc" | "desc";

export interface WorkItem {
  book_id: number;
  title: string;
  author: string;
  author_birth_year: number | null;
  published_year: number | null;
  ndc: string;
  subcorpus: string;
  card_url: string;
}

export interface WorksListResponse {
  total_count: number;
  returned_count: number;
  limit: number;
  offset: number;
  q: string;
  items: WorkItem[];
}

export type ColumnKey =
  | "title"
  | "author"
  | "left_context"
  | "key_text"
  | "right_context"
  | "lemma"
  | "surface"
  | "lemma_reading"
  | "pos"
  | "ctype"
  | "cform"
  | "goshu"
  | "ndc"
  | "published_year"
  | "author_birth_year"
  | "subcorpus"
  | "card_url"
  | "text";

export interface ColumnDef {
  key: ColumnKey;
  label: string;
}

export const COLUMN_DEFINITIONS: ColumnDef[] = [
  { key: "title", label: "作品名" },
  { key: "author", label: "著者" },
  { key: "left_context", label: "前文脈" },
  { key: "key_text", label: "キー" },
  { key: "right_context", label: "後文脈" },
  { key: "lemma", label: "語彙素" },
  { key: "surface", label: "書字形出現形" },
  { key: "lemma_reading", label: "語彙素読み" },
  { key: "pos", label: "品詞" },
  { key: "ctype", label: "活用型" },
  { key: "cform", label: "活用形" },
  { key: "goshu", label: "語種" },
  { key: "ndc", label: "NDC" },
  { key: "published_year", label: "出版年" },
  { key: "author_birth_year", label: "著者生年" },
  { key: "subcorpus", label: "サブコーパス" },
  { key: "card_url", label: "図書カードURL" },
  { key: "text", label: "文全文" },
];

export const DEFAULT_VISIBLE_COLUMNS: ColumnKey[] = [
  "title",
  "author",
  "left_context",
  "key_text",
  "right_context",
  "lemma",
  "pos",
  "cform",
];

export function createEmptyTokenCondition(): TokenCondition {
  return {
    lemma: "",
    surface: "",
    lemma_reading: "",
    pos: "",
    ctype: "",
    cform: "",
    goshu: "",
    match_mode: "exact",
  };
}
