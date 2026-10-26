/** Typed Gateway client for owner-scoped semantic transcript search. */

import { apiClient } from "../utils/apiClient";

export interface SearchSourceSegment {
  index: number;
  speaker: string | null;
  start_ms: number | null;
  end_ms: number | null;
}

export interface SemanticSearchResult {
  meeting_id: string;
  transcript_id: string;
  chunk_id: string;
  chunk_index: number;
  text: string;
  language: string | null;
  source_segments: SearchSourceSegment[];
  start_ms: number | null;
  end_ms: number | null;
  score: number;
}

export interface SemanticSearchResponse {
  results: SemanticSearchResult[];
}

export interface SemanticSearchRequest {
  query: string;
  top_k?: number;
  meeting_ids?: string[];
}

export const searchApi = {
  search: (query: string) =>
    apiClient.post<SemanticSearchResponse>("search", { query } satisfies SemanticSearchRequest),
};
