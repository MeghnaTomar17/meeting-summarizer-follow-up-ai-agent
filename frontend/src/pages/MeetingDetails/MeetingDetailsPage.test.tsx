import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import MeetingDetailsPage from "./index";
import { meetingApi } from "../../services/meetingApi";
import { ApiError } from "../../utils/apiClient";

vi.mock("../../services/meetingApi", () => ({
  meetingApi: {
    getById: vi.fn(), getTranscript: vi.fn(), getSummary: vi.fn(), listTasks: vi.fn(),
    listDecisions: vi.fn(), listInsights: vi.fn(), listFollowups: vi.fn(), getProcessingStatus: vi.fn(),
  },
}));

const meeting = { id: "meeting-1", title: "Planning", description: null, scheduled_at: null, participants: [], status: "ready" as const, created_at: "2026-10-20T10:00:00Z", updated_at: "2026-10-20T10:00:00Z" };
const page = { items: [], pagination: { page: 1, page_size: 20, total: 0, total_pages: 0 } };
function renderPage() { return render(<MemoryRouter initialEntries={["/meetings/meeting-1"]}><Routes><Route path="/meetings/:meetingId" element={<MeetingDetailsPage />} /></Routes></MemoryRouter>); }

describe("MeetingDetailsPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(meetingApi.getById).mockResolvedValue(meeting);
    vi.mocked(meetingApi.getTranscript).mockResolvedValue({ id: "t1", meeting_id: "meeting-1", segments: [{ index: 0, speaker: "Sam", text: "Launch is next week.", start_ms: 1000, end_ms: 2000 }], language: "en", created_at: "2026-10-20T10:00:00Z", updated_at: "2026-10-20T10:00:00Z" });
    vi.mocked(meetingApi.getProcessingStatus).mockResolvedValue({ meeting_id: "meeting-1", status: null, updated_at: null, completed_at: null });
    vi.mocked(meetingApi.getSummary).mockRejectedValue(new ApiError("not found", 404));
    vi.mocked(meetingApi.listTasks).mockResolvedValue(page);
    vi.mocked(meetingApi.listDecisions).mockResolvedValue(page);
    vi.mocked(meetingApi.listInsights).mockResolvedValue(page);
    vi.mocked(meetingApi.listFollowups).mockResolvedValue(page);
  });

  it("renders meeting metadata and transcript, and navigates between sections", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "Planning" })).toBeInTheDocument();
    expect(await screen.findByText("Launch is next week.")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("tab", { name: "Tasks" }));
    expect(await screen.findByText("No tasks available.")).toBeInTheDocument();
    expect(meetingApi.listTasks).toHaveBeenCalledWith("meeting-1");
  });

  it("shows a graceful empty state for a missing optional summary", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Summary" }));
    expect(await screen.findByText("No summary available.")).toBeInTheDocument();
  });

  it("shows loading and retries section failures", async () => {
    vi.mocked(meetingApi.listTasks).mockRejectedValueOnce(new Error("offline")).mockResolvedValue(page);
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Tasks" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to load this section");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No tasks available.")).toBeInTheDocument();
  });

  it("exposes the section loading state", async () => {
    vi.mocked(meetingApi.listTasks).mockReturnValue(new Promise(() => undefined));
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Tasks" }));
    expect(screen.getByRole("status")).toHaveTextContent("Loading tasks");
  });

  it("shows and conservatively polls an actual running job status", async () => {
    vi.useFakeTimers();
    vi.mocked(meetingApi.getProcessingStatus).mockResolvedValue({ meeting_id: "meeting-1", status: "running", updated_at: "2026-10-20T10:00:00Z", completed_at: null });
    renderPage();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(meetingApi.getProcessingStatus).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(meetingApi.getProcessingStatus).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });
});
