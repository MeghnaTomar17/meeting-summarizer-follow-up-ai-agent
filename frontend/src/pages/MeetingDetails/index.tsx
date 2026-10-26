import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { ApiError } from "../../utils/apiClient";
import { meetingApi, type DecisionRecord, type FollowupRecord, type InsightRecord, type MeetingDetails as Meeting, type MeetingProcessingStatus, type SummaryRecord, type TaskRecord, type TranscriptRecord } from "../../services/meetingApi";

const tabs = ["Transcript", "Summary", "Tasks", "Decisions", "Insights", "Follow-up"] as const;
type Tab = typeof tabs[number];
type SectionData = TranscriptRecord | SummaryRecord | TaskRecord[] | DecisionRecord[] | InsightRecord[] | FollowupRecord[];
const loaders: Record<Tab, (id: string) => Promise<SectionData>> = {
  Transcript: meetingApi.getTranscript,
  Summary: meetingApi.getSummary,
  Tasks: async (id) => (await meetingApi.listTasks(id)).items,
  Decisions: async (id) => (await meetingApi.listDecisions(id)).items,
  Insights: async (id) => (await meetingApi.listInsights(id)).items,
  "Follow-up": async (id) => (await meetingApi.listFollowups(id)).items,
};

function isMissing(error: unknown): boolean { return error instanceof ApiError && error.status === 404; }
function formatDate(value: string | null | undefined): string { return value ? new Date(value).toLocaleString() : "Not scheduled"; }

export default function MeetingDetailsPage() {
  const { meetingId = "" } = useParams();
  const location = useLocation();
  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [meetingError, setMeetingError] = useState<string | null>(null);
  const [meetingAttempt, setMeetingAttempt] = useState(0);
  const [activeTab, setActiveTab] = useState<Tab>("Transcript");
  const [sections, setSections] = useState<Partial<Record<Tab, { data?: SectionData; error?: string; loading?: boolean; empty?: boolean }>>>({});
  const [sectionAttempt, setSectionAttempt] = useState(0);
  const [processing, setProcessing] = useState<MeetingProcessingStatus | null>(null);
  const [processingError, setProcessingError] = useState(false);
  const [statusAttempt, setStatusAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setMeeting(null); setMeetingError(null);
    void meetingApi.getById(meetingId).then((value) => { if (active) setMeeting(value); }).catch(() => { if (active) setMeetingError("Unable to load this meeting. Try again."); });
    return () => { active = false; };
  }, [meetingId, meetingAttempt]);

  useEffect(() => {
    let active = true;
    setSections((current) => ({ ...current, [activeTab]: { loading: true } }));
    void loaders[activeTab](meetingId).then((data) => {
      if (!active) return;
      const empty = Array.isArray(data) ? data.length === 0 : false;
      setSections((current) => ({ ...current, [activeTab]: { data, empty } }));
    }).catch((error: unknown) => {
      if (!active) return;
      setSections((current) => ({ ...current, [activeTab]: isMissing(error) ? { empty: true } : { error: "Unable to load this section. Try again." } }));
    });
    return () => { active = false; };
  }, [meetingId, activeTab, sectionAttempt]);

  const refreshStatus = useCallback(async (active: () => boolean): Promise<MeetingProcessingStatus | null> => {
    try { const status = await meetingApi.getProcessingStatus(meetingId); if (active()) { setProcessing(status); setProcessingError(false); } return status; }
    catch { if (active()) { setProcessing(null); setProcessingError(true); } return null; }
  }, [meetingId]);
  useEffect(() => {
    let mounted = true;
    let timer: number | undefined;
    const poll = async () => {
      const status = await refreshStatus(() => mounted);
      if (mounted && (status?.status === "queued" || status?.status === "running")) timer = window.setTimeout(() => void poll(), 5000);
    };
    void poll();
    return () => { mounted = false; if (timer !== undefined) window.clearTimeout(timer); };
  }, [refreshStatus, statusAttempt]);

  const section = sections[activeTab];
  return <section className="detail-page" aria-labelledby="meeting-detail-title">
    <Link to="/meetings">← Back to meetings</Link>
    {(location.state as { notice?: string } | null)?.notice && <p role="status">{(location.state as { notice: string }).notice}</p>}
    {meetingError ? <div role="alert" className="dashboard-message dashboard-error"><p>{meetingError}</p><button className="button button-primary" onClick={() => setMeetingAttempt((n) => n + 1)} type="button">Retry</button></div> : !meeting ? <p role="status">Loading meeting…</p> : <>
      <header className="detail-heading"><div><p className="eyebrow">Meeting</p><h1 id="meeting-detail-title">{meeting.title}</h1></div><span className={`status-pill status-${meeting.status}`}>{meeting.status.replaceAll("_", " ")}</span></header>
      <dl className="meeting-metadata"><div><dt>Date</dt><dd>{formatDate(meeting.scheduled_at)}</dd></div><div><dt>Participants</dt><dd>{meeting.participants.length ? meeting.participants.join(", ") : "None listed"}</dd></div><div><dt>Description</dt><dd>{meeting.description || "No description"}</dd></div><div><dt>Processing status</dt><dd>{processingError ? <>Status unavailable. <button className="button button-quiet" type="button" onClick={() => setStatusAttempt((n) => n + 1)}>Retry</button></> : processing?.status ? <span className={`status-pill status-${processing.status}`}>{processing.status}</span> : "No processing job"}{processing?.updated_at && <small> Updated {formatDate(processing.updated_at)}</small>}</dd></div></dl>
      <div className="detail-tabs" role="tablist" aria-label="Meeting details">
        {tabs.map((tab) => <button key={tab} role="tab" id={`tab-${tab.toLowerCase().replaceAll(" ", "-")}`} aria-selected={activeTab === tab} onClick={() => { setActiveTab(tab); setSectionAttempt(0); }} type="button">{tab}</button>)}
      </div>
      <section className="detail-section" role="tabpanel" aria-labelledby={`tab-${activeTab.toLowerCase().replaceAll(" ", "-")}`}>
        <h2>{activeTab}</h2>
        {section?.loading && <p role="status">Loading {activeTab.toLowerCase()}…</p>}
        {section?.error && <div role="alert" className="dashboard-message dashboard-error"><p>{section.error}</p><button className="button button-primary" type="button" onClick={() => setSectionAttempt((n) => n + 1)}>Retry</button></div>}
        {section?.empty && <p className="meetings-empty">No {activeTab.toLowerCase()} available.</p>}
        {section?.data && <SectionContent tab={activeTab} data={section.data} />}
      </section>
    </>}
  </section>;
}

function SectionContent({ tab, data }: { tab: Tab; data: SectionData }) {
  if (tab === "Transcript") {
    const transcript = data as TranscriptRecord;
    return <div className="transcript-list">{transcript.segments.length ? transcript.segments.map((segment) => <article key={segment.index}><p className="muted">{segment.speaker || "Speaker"}{segment.start_ms !== null ? ` · ${Math.floor(segment.start_ms / 1000)}s` : ""}</p><p>{segment.text}</p></article>) : <p className="meetings-empty">Transcript has no segments.</p>}</div>;
  }
  if (tab === "Summary") { const summary = data as SummaryRecord; return <article><p>{summary.content}</p>{summary.key_topics.length > 0 && <p><strong>Key topics:</strong> {summary.key_topics.join(", ")}</p>}</article>; }
  if (tab === "Tasks") return <ul className="detail-list">{(data as TaskRecord[]).map((item) => <li key={item.id}><strong>{item.title}</strong> <span className="status-pill">{item.status.replaceAll("_", " ")}</span>{item.description && <p>{item.description}</p>}{item.due_at && <small>Due {formatDate(item.due_at)}</small>}</li>)}</ul>;
  if (tab === "Decisions") return <ul className="detail-list">{(data as DecisionRecord[]).map((item) => <li key={item.id}><strong>{item.statement}</strong>{item.context && <p>{item.context}</p>}</li>)}</ul>;
  if (tab === "Insights") return <ul className="detail-list">{(data as InsightRecord[]).map((item) => <li key={item.id}><strong>{item.title}</strong> <span className="status-pill">{item.category}</span><p>{item.description}</p></li>)}</ul>;
  return <ul className="detail-list">{(data as FollowupRecord[]).map((item) => <li key={item.id}><strong>{item.subject}</strong> <span className="status-pill">{item.status}</span><p>Recipients: {item.recipients.join(", ") || "None listed"}</p>{item.scheduled_at && <small>Scheduled {formatDate(item.scheduled_at)}</small>}</li>)}</ul>;
}
