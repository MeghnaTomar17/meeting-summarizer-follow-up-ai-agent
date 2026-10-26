import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import AnalyticsPage from "./index";
import { analyticsApi } from "../../services/analyticsApi";

vi.mock("../../services/analyticsApi", () => ({
  analyticsApi: {
    getOverview: vi.fn(),
    getTrends: vi.fn(),
    getTaskCompletionTrends: vi.fn(),
  },
}));

const overview = {
  total_meetings: 4,
  meetings_per_week: [
    { week_start: "2026-10-05", count: 2 },
    { week_start: "2026-10-12", count: 0 },
    { week_start: "2026-10-19", count: 1 },
  ],
  open_tasks: 3,
  completed_tasks: 5,
  overdue_tasks: 1,
  decisions: 6,
  followups: 0,
  followup_status_counts: {},
  meeting_status_counts: {},
  processing_job_status_counts: {},
};
const trends = {
  decision_trends: [
    { week_start: "2026-10-05", count: 1 },
    { week_start: "2026-10-12", count: 3 },
    { week_start: "2026-10-19", count: 0 },
  ],
  meeting_frequency: overview.meetings_per_week,
  topic_trends: [
    { week_start: "2026-10-05", topics: [{ topic: "Hiring", count: 2 }, { topic: "Budget", count: 1 }] },
    { week_start: "2026-10-12", topics: [{ topic: "Hiring", count: 1 }] },
    { week_start: "2026-10-19", topics: [] },
  ],
};
const taskCompletion = { available: false as const, reason: "No completion timestamp or status-transition history is recorded." };

function resolveAnalytics() {
  vi.mocked(analyticsApi.getOverview).mockResolvedValue(overview);
  vi.mocked(analyticsApi.getTrends).mockResolvedValue(trends);
  vi.mocked(analyticsApi.getTaskCompletionTrends).mockResolvedValue(taskCompletion);
}

describe("AnalyticsPage", () => {
  beforeEach(() => vi.resetAllMocks());

  it("maps weekly meetings, decisions, current task counts, unavailable history, and exact topic totals", async () => {
    resolveAnalytics();
    render(<AnalyticsPage />);

    expect(await screen.findByRole("img", { name: /Meetings per week\. 2026-10-05: 2, 2026-10-12: 0, 2026-10-19: 1/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Decisions over time\. 2026-10-05: 1, 2026-10-12: 3, 2026-10-19: 0/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Open versus completed tasks\. Open \(including in progress\): 3, Completed: 5/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Tasks completed over time" })).toBeInTheDocument();
    expect(screen.getByText(/Historical completion events are not currently recorded/)).toBeInTheDocument();
    expect(screen.getByText(/No completion timestamp or status-transition history/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Recurring topics\. Hiring: 3, Budget: 1/ })).toBeInTheDocument();
    expect(screen.getByText(/Exact normalized topic strings/)).toBeInTheDocument();
    expect(analyticsApi.getOverview).toHaveBeenCalledTimes(1);
    expect(analyticsApi.getTrends).toHaveBeenCalledTimes(1);
    expect(analyticsApi.getTaskCompletionTrends).toHaveBeenCalledTimes(1);
  });

  it("shows loading, then a readable empty-data state", async () => {
    vi.mocked(analyticsApi.getOverview).mockReturnValue(new Promise(() => undefined));
    vi.mocked(analyticsApi.getTrends).mockReturnValue(new Promise(() => undefined));
    vi.mocked(analyticsApi.getTaskCompletionTrends).mockReturnValue(new Promise(() => undefined));
    const view = render(<AnalyticsPage />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading analytics");
    view.unmount();

    vi.mocked(analyticsApi.getOverview).mockResolvedValue({ ...overview, meetings_per_week: [], open_tasks: 0, completed_tasks: 0 });
    vi.mocked(analyticsApi.getTrends).mockResolvedValue({
      decision_trends: [], meeting_frequency: [], topic_trends: [],
    });
    vi.mocked(analyticsApi.getTaskCompletionTrends).mockResolvedValue(taskCompletion);
    render(<AnalyticsPage />);
    expect(await screen.findByText("No meeting activity in the returned weekly window.")).toBeInTheDocument();
    expect(screen.getByText("No open or completed tasks are currently recorded.")).toBeInTheDocument();
    expect(screen.getByText("No decisions in the returned weekly window.")).toBeInTheDocument();
    expect(screen.getByText("No persisted summary topics in the returned weekly window.")).toBeInTheDocument();
  });

  it("shows an API error and retries", async () => {
    vi.mocked(analyticsApi.getOverview).mockRejectedValueOnce(new Error("offline")).mockResolvedValue(overview);
    vi.mocked(analyticsApi.getTrends).mockResolvedValue(trends);
    vi.mocked(analyticsApi.getTaskCompletionTrends).mockResolvedValue(taskCompletion);
    render(<AnalyticsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "Meetings per week" })).toBeInTheDocument();
    expect(analyticsApi.getOverview).toHaveBeenCalledTimes(2);
  });

  it("refreshes all analytics endpoints", async () => {
    resolveAnalytics();
    render(<AnalyticsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Refresh" }));
    expect(analyticsApi.getOverview).toHaveBeenCalledTimes(2);
    expect(analyticsApi.getTrends).toHaveBeenCalledTimes(2);
    expect(analyticsApi.getTaskCompletionTrends).toHaveBeenCalledTimes(2);
  });
});
