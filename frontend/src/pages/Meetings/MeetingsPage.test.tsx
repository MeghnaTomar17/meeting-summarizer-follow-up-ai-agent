import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import MeetingsPage from "./index";
import { meetingApi } from "../../services/meetingApi";

vi.mock("../../services/meetingApi", () => ({ meetingApi: { list: vi.fn() } }));

const emptyPage = {
  items: [],
  pagination: { page: 1, page_size: 20, total: 0, total_pages: 0 },
};
const meeting = {
  id: "m1",
  title: "Quarterly Planning",
  scheduled_at: "2026-11-03T09:30:00Z",
  status: "ready" as const,
  processing_status: "completed" as const,
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-20T10:30:00Z",
};

describe("MeetingsPage", () => {
  beforeEach(() => vi.resetAllMocks());

  it("renders meeting fields and both lifecycle statuses", async () => {
    vi.mocked(meetingApi.list).mockResolvedValue({
      items: [meeting], pagination: { page: 1, page_size: 20, total: 1, total_pages: 1 },
    });
    render(<MemoryRouter><MeetingsPage /></MemoryRouter>);
    expect(await screen.findByText("Quarterly Planning")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Processing Status" })).toBeInTheDocument();
    expect(screen.getByText("ready")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByRole("time")).toHaveAttribute("datetime", "2026-11-03T09:30:00Z");
  });

  it("shows a loading state while the request is pending", () => {
    vi.mocked(meetingApi.list).mockReturnValue(new Promise(() => undefined));
    render(<MemoryRouter><MeetingsPage /></MemoryRouter>);
    expect(screen.getByRole("status")).toHaveTextContent("Loading meetings");
  });

  it("shows an error and retries the request", async () => {
    vi.mocked(meetingApi.list).mockRejectedValueOnce(new Error("offline")).mockResolvedValue({
      items: [meeting], pagination: { page: 1, page_size: 20, total: 1, total_pages: 1 },
    });
    render(<MemoryRouter><MeetingsPage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Quarterly Planning")).toBeInTheDocument();
    expect(meetingApi.list).toHaveBeenCalledTimes(2);
  });

  it("shows an empty collection state", async () => {
    vi.mocked(meetingApi.list).mockResolvedValue(emptyPage);
    render(<MemoryRouter><MeetingsPage /></MemoryRouter>);
    expect(await screen.findByText("No meetings yet.")).toBeInTheDocument();
  });

  it("requests the next page when pagination is used", async () => {
    vi.mocked(meetingApi.list)
      .mockResolvedValueOnce({ items: [meeting], pagination: { page: 1, page_size: 20, total: 21, total_pages: 2 } })
      .mockResolvedValueOnce({ items: [{ ...meeting, id: "m2", title: "Retrospective" }], pagination: { page: 2, page_size: 20, total: 21, total_pages: 2 } });
    render(<MemoryRouter><MeetingsPage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Next" }));
    expect(await screen.findByText("Retrospective")).toBeInTheDocument();
    expect(meetingApi.list).toHaveBeenNthCalledWith(2, 2, 20);
  });
});
