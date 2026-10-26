import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import UploadPage from "./index";
import { meetingApi } from "../../services/meetingApi";

vi.mock("../../services/meetingApi", () => ({ meetingApi: { create: vi.fn(), createTranscript: vi.fn() } }));
function Destination() { const location = useLocation(); return <p>At {location.pathname}</p>; }
function renderPage() { return render(<MemoryRouter initialEntries={["/upload"]}><Routes><Route path="/upload" element={<UploadPage />} /><Route path="/meetings/:meetingId" element={<Destination />} /></Routes></MemoryRouter>); }
function fillRequiredFields() {
  fireEvent.change(screen.getByLabelText("Organization ID"), { target: { value: "00000000-0000-4000-8000-000000000001" } });
  fireEvent.change(screen.getByLabelText("Meeting title"), { target: { value: "Planning" } });
  fireEvent.change(screen.getByLabelText("Transcript segments (JSON)"), { target: { value: '[{"index":0,"text":"Discuss launch"}]' } });
}

describe("UploadPage", () => {
  beforeEach(() => { vi.resetAllMocks(); vi.mocked(meetingApi.create).mockResolvedValue({ id: "meeting-1" } as never); vi.mocked(meetingApi.createTranscript).mockResolvedValue({} as never); });
  it("validates JSON segments before creating a meeting", async () => {
    renderPage(); fillRequiredFields();
    fireEvent.change(screen.getByLabelText("Transcript segments (JSON)"), { target: { value: "not json" } });
    fireEvent.click(screen.getByRole("button", { name: "Create meeting and save transcript" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("JSON");
    expect(meetingApi.create).not.toHaveBeenCalled();
  });
  it("creates the meeting, saves JSON segments, and navigates to details", async () => {
    renderPage(); fillRequiredFields();
    fireEvent.click(screen.getByRole("button", { name: "Create meeting and save transcript" }));
    expect(await screen.findByText("At /meetings/meeting-1")).toBeInTheDocument();
    expect(meetingApi.createTranscript).toHaveBeenCalledWith("meeting-1", { language: "en", segments: [{ index: 0, speaker: null, text: "Discuss launch", start_ms: null, end_ms: null }] });
  });
  it("keeps the created meeting id after transcript failure and avoids duplicate creation on retry", async () => {
    vi.mocked(meetingApi.createTranscript).mockRejectedValueOnce(new Error("offline"));
    renderPage(); fillRequiredFields();
    fireEvent.click(screen.getByRole("button", { name: "Create meeting and save transcript" }));
    expect(await screen.findByText("Meeting created. Retrying will submit the transcript to that meeting without creating another.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry transcript save" }));
    await waitFor(() => expect(meetingApi.createTranscript).toHaveBeenCalledTimes(2));
    expect(meetingApi.create).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("At /meetings/meeting-1")).toBeInTheDocument();
  });
});
