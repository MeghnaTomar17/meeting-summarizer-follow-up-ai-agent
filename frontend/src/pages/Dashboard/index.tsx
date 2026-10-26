import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../utils/apiClient";
import { analyticsApi, type AnalyticsOverview, type UpcomingFollowup } from "../../services/analyticsApi";

type DashboardData = { overview: AnalyticsOverview; followups: UpcomingFollowup[]; followupTotal: number };

function messageFor(error: unknown): string {
  return error instanceof ApiError ? error.message : "Unable to load dashboard data. Try again.";
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [overview, followups] = await Promise.all([
        analyticsApi.getOverview(),
        analyticsApi.getUpcomingFollowups(),
      ]);
      setData({ overview, followups: followups.items, followupTotal: followups.pagination.total });
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load, attempt]);

  if (loading) return <section className="dashboard" aria-busy="true"><p role="status">Loading dashboard…</p></section>;
  if (error) return <section className="dashboard"><p className="eyebrow">Overview</p><h1>Dashboard</h1><div className="dashboard-message dashboard-error" role="alert"><p>{error}</p><button className="button button-primary" onClick={() => setAttempt((value) => value + 1)} type="button">Retry</button></div></section>;
  if (!data) return null;

  const cards = [
    ["Total Meetings", data.overview.total_meetings],
    ["Open Tasks", data.overview.open_tasks],
    ["Completed Tasks", data.overview.completed_tasks],
    ["Decisions", data.overview.decisions],
    ["Upcoming Follow-ups", data.followupTotal],
  ] as const;

  return (
    <section className="dashboard" aria-labelledby="dashboard-title">
      <div className="dashboard-heading"><div><p className="eyebrow">Overview</p><h1 id="dashboard-title">Dashboard</h1><p className="muted">A snapshot of your meetings and follow-ups.</p></div><button className="button button-quiet" onClick={() => setAttempt((value) => value + 1)} type="button">Refresh</button></div>
      <div className="metric-grid">{cards.map(([label, value]) => <article className="metric-card" key={label}><h2>{label}</h2><p>{value.toLocaleString()}</p></article>)}</div>
      <section className="followups-panel" aria-labelledby="upcoming-title">
        <div className="panel-heading"><div><p className="eyebrow">Schedule</p><h2 id="upcoming-title">Upcoming follow-ups</h2></div><span className="muted">{data.followupTotal} scheduled</span></div>
        {data.followups.length === 0 ? <p className="dashboard-empty">No upcoming follow-ups.</p> : <ul className="followup-list">{data.followups.map((item) => <li key={item.id}><span className="followup-subject">{item.subject}</span><time dateTime={item.scheduled_at}>{formatDate(item.scheduled_at)}</time></li>)}</ul>}
        {data.followupTotal > data.followups.length && <p className="muted">Showing the next {data.followups.length} of {data.followupTotal}.</p>}
      </section>
    </section>
  );
}
