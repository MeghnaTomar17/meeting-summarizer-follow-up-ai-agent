import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import SearchPage from "./index";
import { searchApi, type SemanticSearchResult } from "../../services/searchApi";
import { ApiError } from "../../utils/apiClient";

vi.mock("../../services/searchApi", () => ({ searchApi: { search: vi.fn() } }));

const match = (overrides: Partial<SemanticSearchResult> = {}): SemanticSearchResult => ({
  meeting_id: "00000000-0000-4000-8000-000000000001",
  transcript_id: "00000000-0000-4000-8000-000000000002",
  chunk_id: "00000000-0000-4000-8000-000000000003",
  chunk_index: 0,
  text: "The team approved the hiring plan.",
  language: "en",
  source_segments: [{ index: 4, speaker: "Sam", start_ms: 62000, end_ms: 67000 }],
  start_ms: 62000,
  end_ms: 67000,
  score: 0.87,
  ...overrides,
});

function renderPage() { return render(<MemoryRouter><SearchPage /></MemoryRouter>); }
function submitQuery(value: string) {
  fireEvent.change(screen.getByRole("searchbox", { name: "Search query" }), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
}

describe("SearchPage", () => {
  beforeEach(() => vi.resetAllMocks());

  it("submits a query and renders the returned snippet, raw score, source, and details link", async () => {
    vi.mocked(searchApi.search).mockResolvedValue({ results: [match()] });
    renderPage();
    submitQuery("  hiring plan  ");
    expect(await screen.findByText("The team approved the hiring plan.")).toBeInTheDocument();
    expect(screen.getByText("Similarity score: 0.87")).toHaveAttribute("title", "Raw Qdrant score; higher is more similar");
    expect(screen.getByText(/00000000-0000-4000-8000-000000000001/)).toBeInTheDocument();
    expect(screen.getByText("Transcript time: 1:02–1:07")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open meeting details" })).toHaveAttribute("href", "/meetings/00000000-0000-4000-8000-000000000001");
    expect(searchApi.search).toHaveBeenCalledWith("hiring plan");
  });

  it("shows an empty-results state", async () => {
    vi.mocked(searchApi.search).mockResolvedValue({ results: [] });
    renderPage();
    submitQuery("unmentioned topic");
    expect(await screen.findByText("No matching transcript excerpts found.")).toBeInTheDocument();
  });

  it("shows loading and allows retry after an API error", async () => {
    vi.mocked(searchApi.search).mockRejectedValueOnce(new ApiError("Search service is unavailable.", 503)).mockResolvedValue({ results: [match()] });
    renderPage();
    submitQuery("hiring");
    expect(screen.getByRole("status")).toHaveTextContent("Searching transcripts");
    fireEvent.click(await screen.findByRole("button", { name: "Retry search" }));
    expect(await screen.findByText("The team approved the hiring plan.")).toBeInTheDocument();
    expect(searchApi.search).toHaveBeenCalledTimes(2);
  });

  it("validates blank queries without making an API request", async () => {
    renderPage();
    submitQuery("   ");
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a search query.");
    expect(searchApi.search).not.toHaveBeenCalled();
  });

  it("keeps newer results when overlapping searches resolve out of order", async () => {
    const resolvers: Array<(value: { results: SemanticSearchResult[] }) => void> = [];
    vi.mocked(searchApi.search).mockImplementation(() => new Promise((resolve) => resolvers.push(resolve)));
    renderPage();
    submitQuery("first query");
    submitQuery("second query");
    expect(searchApi.search).toHaveBeenCalledTimes(2);

    resolvers[1]({ results: [match({ text: "Second query result.", chunk_id: "second-chunk" })] });
    expect(await screen.findByText("Second query result.")).toBeInTheDocument();
    resolvers[0]({ results: [match({ text: "Stale first result.", chunk_id: "first-chunk" })] });
    await waitFor(() => expect(screen.queryByText("Stale first result.")).not.toBeInTheDocument());
    expect(screen.getByText("Second query result.")).toBeInTheDocument();
  });

  it("ignores an in-flight response after the user edits the query", async () => {
    let resolveRequest!: (value: { results: SemanticSearchResult[] }) => void;
    vi.mocked(searchApi.search).mockImplementation(() => new Promise((resolve) => { resolveRequest = resolve; }));
    renderPage();
    submitQuery("first query");
    fireEvent.change(screen.getByRole("searchbox", { name: "Search query" }), { target: { value: "new query" } });
    resolveRequest({ results: [match({ text: "Outdated result." })] });
    await waitFor(() => expect(screen.queryByText("Outdated result.")).not.toBeInTheDocument());
    expect(screen.getByRole("searchbox", { name: "Search query" })).toHaveValue("new query");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
