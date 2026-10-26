import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { meetingApi, type TranscriptInput, type TranscriptSegment } from "../../services/meetingApi";
import { ApiError } from "../../utils/apiClient";

const initialSegments = JSON.stringify([{ index: 0, speaker: null, text: "", start_ms: null, end_ms: null }], null, 2);

function validateSegments(raw: string): TranscriptSegment[] {
  const parsed: unknown = JSON.parse(raw);
  if (!Array.isArray(parsed) || parsed.length === 0) throw new Error("Provide at least one transcript segment.");
  const indexes = new Set<number>();
  for (const segment of parsed) {
    if (!segment || typeof segment !== "object") throw new Error("Each segment must be an object.");
    const item = segment as Record<string, unknown>;
    if (!Number.isInteger(item.index) || (item.index as number) < 0 || typeof item.text !== "string" || !item.text.trim()) throw new Error("Each segment needs a nonnegative integer index and nonblank text.");
    if (indexes.has(item.index as number)) throw new Error("Segment indexes must be unique.");
    indexes.add(item.index as number);
    if (item.speaker !== undefined && item.speaker !== null && typeof item.speaker !== "string") throw new Error("Speaker must be text or null.");
    for (const key of ["start_ms", "end_ms"]) if (item[key] !== undefined && item[key] !== null && (!Number.isInteger(item[key]) || (item[key] as number) < 0)) throw new Error("Segment times must be nonnegative integer milliseconds or null.");
    if (item.start_ms != null && item.end_ms != null && (item.end_ms as number) < (item.start_ms as number)) throw new Error("Segment end time cannot precede its start time.");
  }
  const ordered = [...parsed].sort((a, b) => (a.index as number) - (b.index as number));
  if (ordered.some((item, index) => item !== parsed[index])) throw new Error("Segments must be ordered by index.");
  return parsed.map((item) => ({ index: item.index as number, speaker: (item.speaker as string | null | undefined) ?? null, text: item.text as string, start_ms: (item.start_ms as number | null | undefined) ?? null, end_ms: (item.end_ms as number | null | undefined) ?? null }));
}

export default function UploadPage() {
  const navigate = useNavigate();
  const [organizationId, setOrganizationId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [scheduledAt, setScheduledAt] = useState("");
  const [participants, setParticipants] = useState("");
  const [language, setLanguage] = useState("en");
  const [segments, setSegments] = useState(initialSegments);
  const [createdMeetingId, setCreatedMeetingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault(); setError(null);
    let transcript: TranscriptInput;
    try { transcript = { language: language.trim() || "en", segments: validateSegments(segments) }; }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Transcript segments are invalid."); return; }
    if (!organizationId.trim() || !title.trim()) { setError("Organization ID and meeting title are required."); return; }
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(organizationId.trim())) { setError("Enter a valid organization UUID."); return; }
    setBusy(true);
    try {
      const meeting = createdMeetingId ? { id: createdMeetingId } : await meetingApi.create({
        organization_id: organizationId.trim(), title: title.trim(), description: description.trim() || undefined,
        scheduled_at: scheduledAt ? new Date(scheduledAt).toISOString() : undefined,
        participants: participants.split(",").map((value) => value.trim()).filter(Boolean),
      });
      if (!createdMeetingId) setCreatedMeetingId(meeting.id);
      await meetingApi.createTranscript(meeting.id, transcript);
      navigate(`/meetings/${encodeURIComponent(meeting.id)}`, { state: { notice: "Transcript saved. This action does not start background processing." } });
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Unable to save the meeting and transcript. Try again.");
    } finally { setBusy(false); }
  }

  return <section className="upload-page" aria-labelledby="upload-title">
    <p className="eyebrow">Workspace</p><h1 id="upload-title">Add a meeting transcript</h1>
    <p className="muted">The current API accepts JSON transcript segments. It does not accept transcript files or start processing.</p>
    {createdMeetingId && <p role="status">Meeting created. Retrying will submit the transcript to that meeting without creating another.</p>}
    {error && <div role="alert" className="dashboard-message dashboard-error"><p>{error}</p></div>}
    <form className="upload-form" onSubmit={(event) => void submit(event)}>
      <label>Organization ID<input required value={organizationId} onChange={(event) => setOrganizationId(event.target.value)} /></label>
      <label>Meeting title<input required value={title} onChange={(event) => setTitle(event.target.value)} /></label>
      <label>Description<input value={description} onChange={(event) => setDescription(event.target.value)} /></label>
      <label>Meeting date and time<input type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} /></label>
      <label>Participants (comma-separated)<input value={participants} onChange={(event) => setParticipants(event.target.value)} /></label>
      <label>Transcript language<input value={language} onChange={(event) => setLanguage(event.target.value)} /></label>
      <label>Transcript segments (JSON)<textarea required rows={12} value={segments} onChange={(event) => setSegments(event.target.value)} spellCheck={false} /></label>
      <p className="field-hint">Each item uses index, text, and optional speaker, start_ms, and end_ms fields. Include at least one nonblank segment.</p>
      <button className="button button-primary" type="submit" disabled={busy}>{busy ? "Saving…" : createdMeetingId ? "Retry transcript save" : "Create meeting and save transcript"}</button>
    </form>
    <p><Link to="/meetings">Cancel</Link></p>
  </section>;
}
