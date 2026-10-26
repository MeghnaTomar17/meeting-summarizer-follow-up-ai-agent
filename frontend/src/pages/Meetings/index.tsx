import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../utils/apiClient";
import { meetingApi, type MeetingListItem, type MeetingListResponse } from "../../services/meetingApi";

const PAGE_SIZE = 20;

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Unable to load meetings. Try again.";
}

function meetingDate(value: string | null): string {
  if (!value) return "Not scheduled";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function Status({ children }: { children: string }) {
  return <span className={`status-pill status-${children}`}>{children.replaceAll("_", " ")}</span>;
}

export default function MeetingsPage() {
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<MeetingListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setResult(await meetingApi.list(page, PAGE_SIZE));
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => { void load(); }, [load, attempt]);

  const changePage = (next: number) => {
    setPage(next);
    setAttempt(0);
  };

  return (
    <section className="meetings-page" aria-labelledby="meetings-title">
      <div className="meetings-heading"><div><p className="eyebrow">Workspace</p><h1 id="meetings-title">Meetings</h1><p className="muted">Your meetings and their processing progress.</p></div><button className="button button-quiet" onClick={() => setAttempt((value) => value + 1)} type="button" disabled={loading}>Refresh</button></div>
      {loading && <p className="meetings-message" role="status" aria-busy="true">Loading meetings…</p>}
      {!loading && error && <div className="dashboard-message dashboard-error" role="alert"><p>{error}</p><button className="button button-primary" onClick={() => setAttempt((value) => value + 1)} type="button">Retry</button></div>}
      {!loading && !error && result && result.items.length === 0 && <p className="meetings-empty">{result.pagination.total === 0 ? "No meetings yet." : "No meetings on this page."}</p>}
      {!loading && !error && result && result.items.length > 0 && <>
        <div className="meetings-table-wrap"><table className="meetings-table"><thead><tr><th scope="col">Title</th><th scope="col">Date</th><th scope="col">Status</th><th scope="col">Processing Status</th></tr></thead>
          <tbody>{result.items.map((meeting: MeetingListItem) => <tr key={meeting.id}><th scope="row" data-label="Title">{meeting.title}</th><td data-label="Date">{meeting.scheduled_at ? <time dateTime={meeting.scheduled_at}>{meetingDate(meeting.scheduled_at)}</time> : "Not scheduled"}</td><td data-label="Status"><Status>{meeting.status}</Status></td><td data-label="Processing Status">{meeting.processing_status ? <Status>{meeting.processing_status}</Status> : <span aria-label="No processing job">—</span>}</td></tr>)}</tbody>
        </table></div>
        <div className="pagination-controls" aria-label="Meeting list pagination"><span className="muted">Page {result.pagination.page} of {Math.max(1, result.pagination.total_pages)} · {result.pagination.total} meetings</span><div><button className="button button-quiet" disabled={loading || page <= 1} onClick={() => changePage(page - 1)} type="button">Previous</button><button className="button button-quiet" disabled={loading || page >= result.pagination.total_pages} onClick={() => changePage(page + 1)} type="button">Next</button></div></div>
      </>}
    </section>
  );
}
