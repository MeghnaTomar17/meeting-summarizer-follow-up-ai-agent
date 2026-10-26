import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { searchApi, type SemanticSearchResult } from "../../services/searchApi";
import { ApiError } from "../../utils/apiClient";

const MAX_QUERY_LENGTH = 2000;

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Unable to search meetings. Try again.";
}

function sourceTime(startMs: number | null, endMs: number | null): string | null {
  if (startMs === null && endMs === null) return null;
  const format = (value: number | null) => value === null ? null : `${Math.floor(value / 60000)}:${String(Math.floor((value % 60000) / 1000)).padStart(2, "0")}`;
  const start = format(startMs);
  const end = format(endMs);
  return start && end ? `${start}–${end}` : start || end;
}

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [results, setResults] = useState<SemanticSearchResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const requestSequence = useRef(0);

  useEffect(() => () => { requestSequence.current += 1; }, []);

  async function runSearch(value: string) {
    const requestId = ++requestSequence.current;
    const normalized = value.trim();
    if (!normalized) {
      setValidationError("Enter a search query.");
      setResults(null);
      setSubmittedQuery("");
      setError(null);
      setLoading(false);
      return;
    }
    if (normalized.length > MAX_QUERY_LENGTH) {
      setValidationError(`Search queries must be ${MAX_QUERY_LENGTH} characters or fewer.`);
      setResults(null);
      setSubmittedQuery("");
      setError(null);
      setLoading(false);
      return;
    }

    setValidationError(null);
    setError(null);
    setSubmittedQuery(normalized);
    setResults(null);
    setLoading(true);
    try {
      const response = await searchApi.search(normalized);
      if (requestId === requestSequence.current) setResults(response.results);
    } catch (reason) {
      if (requestId === requestSequence.current) setError(errorMessage(reason));
    } finally {
      if (requestId === requestSequence.current) setLoading(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void runSearch(query);
  }

  return (
    <section className="search-page" aria-labelledby="search-title">
      <header className="search-heading">
        <div><p className="eyebrow">Workspace</p><h1 id="search-title">Search meetings</h1>
          <p className="muted">Find relevant transcript excerpts across your meetings.</p></div>
      </header>
      <form className="search-form" onSubmit={submit} noValidate>
        <label htmlFor="meeting-search-query">Search query</label>
        <div className="search-controls">
          <input
            id="meeting-search-query"
            type="search"
            value={query}
            maxLength={MAX_QUERY_LENGTH}
            onChange={(event) => {
              requestSequence.current += 1;
              setQuery(event.target.value);
              setValidationError(null);
              setSubmittedQuery("");
              setResults(null);
              setError(null);
              setLoading(false);
            }}
            placeholder="What did we decide about hiring?"
            aria-describedby={validationError ? "search-validation-error" : "search-score-help"}
          />
          <button className="button button-primary" type="submit">Search</button>
        </div>
        {validationError
          ? <p id="search-validation-error" className="form-message form-error" role="alert">{validationError}</p>
          : <p id="search-score-help" className="field-hint">Scores are raw vector-search scores; higher means more similar. They are not percentages, and their range depends on the configured distance metric.</p>}
      </form>

      {loading && <p className="search-message" role="status" aria-busy="true">Searching transcripts…</p>}
      {!loading && error && <div className="dashboard-message dashboard-error" role="alert">
        <p>{error}</p><button className="button button-primary" type="button" onClick={() => void runSearch(submittedQuery)}>Retry search</button>
      </div>}
      {!loading && results && results.length === 0 && <p className="search-message">No matching transcript excerpts found.</p>}
      {!loading && results && results.length > 0 && <>
        <p className="search-result-count" role="status">{results.length} {results.length === 1 ? "result" : "results"} for “{submittedQuery}”</p>
        <ol className="search-results">
          {results.map((result) => {
            const time = sourceTime(result.start_ms, result.end_ms);
            return <li className="search-result-card" key={result.chunk_id}>
              <div className="search-result-topline">
                <span className="search-score" title="Raw Qdrant score; higher is more similar">Similarity score: {result.score}</span>
                {result.language && <span className="search-language">{result.language}</span>}
              </div>
              <blockquote>{result.text}</blockquote>
              <div className="search-source">
                <span>Source meeting: <code>{result.meeting_id}</code></span>
                {time && <span>Transcript time: {time}</span>}
                <Link to={`/meetings/${encodeURIComponent(result.meeting_id)}`}>Open meeting details</Link>
              </div>
            </li>;
          })}
        </ol>
      </>}
    </section>
  );
}
