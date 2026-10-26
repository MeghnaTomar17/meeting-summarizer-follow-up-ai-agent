import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import DashboardPage from "./index";
import { analyticsApi } from "../../services/analyticsApi";

vi.mock("../../services/analyticsApi", () => ({
  analyticsApi: { getOverview: vi.fn(), getUpcomingFollowups: vi.fn() },
}));

const overview = { total_meetings: 12, meetings_per_week: [], open_tasks: 4, completed_tasks: 7, decisions: 9 };
const emptyFollowups = { items: [], pagination: { page: 1, page_size: 5, total: 0, total_pages: 0 } };

describe("DashboardPage", () => {
  beforeEach(() => vi.resetAllMocks());

  it("renders overview cards and upcoming items", async () => {
    vi.mocked(analyticsApi.getOverview).mockResolvedValue(overview);
    vi.mocked(analyticsApi.getUpcomingFollowups).mockResolvedValue({
      items: [{ id: "f1", meeting_id: "m1", subject: "Send notes", scheduled_at: "2026-11-01T10:00:00Z", status: "scheduled" }],
      pagination: { page: 1, page_size: 5, total: 1, total_pages: 1 },
    });
    render(<DashboardPage />);
    expect(await screen.findByText("Send notes")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Total Meetings" })).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByRole("time")).toHaveAttribute("datetime", "2026-11-01T10:00:00Z");
  });

  it("shows loading state while requests are pending", () => {
    vi.mocked(analyticsApi.getOverview).mockReturnValue(new Promise(() => undefined));
    vi.mocked(analyticsApi.getUpcomingFollowups).mockReturnValue(new Promise(() => undefined));
    render(<DashboardPage />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading dashboard");
  });

  it("shows a retry action when requests fail", async () => {
    vi.mocked(analyticsApi.getOverview).mockRejectedValueOnce(new Error("offline")).mockResolvedValue(overview);
    vi.mocked(analyticsApi.getUpcomingFollowups).mockResolvedValue(emptyFollowups);
    render(<DashboardPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(analyticsApi.getOverview).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("heading", { name: "Open Tasks" })).toBeInTheDocument();
  });

  it("supports an empty upcoming-followups result", async () => {
    vi.mocked(analyticsApi.getOverview).mockResolvedValue(overview);
    vi.mocked(analyticsApi.getUpcomingFollowups).mockResolvedValue(emptyFollowups);
    render(<DashboardPage />);
    expect(await screen.findByText("No upcoming follow-ups.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Upcoming Follow-ups" })).toBeInTheDocument();
  });
});
