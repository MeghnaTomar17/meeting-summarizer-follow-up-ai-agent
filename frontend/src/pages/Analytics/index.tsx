import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../utils/apiClient";
import {
  analyticsApi,
  type AnalyticsOverview,
  type AnalyticsTrends,
  type TaskCompletionTrends,
} from "../../services/analyticsApi";

type AnalyticsData = { overview: AnalyticsOverview; trends: AnalyticsTrends; taskCompletion: TaskCompletionTrends };
type SeriesPoint = { label: string; value: number; fullDate?: string };

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Unable to load analytics. Try again.";
}

function weekLabel(value: string): string {
  // The API value is already the UTC calendar date that defines the week.
  return value;
}

function titleId(title: string): string {
  return `analytics-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "")}`;
}

function BarChart({ title, description, points, emptyMessage }: {
  title: string; description: string; points: SeriesPoint[]; emptyMessage: string;
}) {
  const id = titleId(title);
  const maximum = Math.max(0, ...points.map((point) => point.value));
  return <section className="analytics-panel" aria-labelledby={id}>
    <h2 id={id}>{title}</h2><p className="analytics-description">{description}</p>
    {points.length === 0 || maximum === 0
      ? <p className="analytics-empty">{emptyMessage}</p>
      : <div className="analytics-bars" role="img" aria-label={`${title}. ${points.map((point) => `${point.label}: ${point.value}`).join(", ")}`}>
        {points.map((point) => <div className="analytics-bar-row" key={`${point.label}-${point.fullDate ?? ""}`}>
          <span className="analytics-bar-label" title={point.fullDate}>{point.label}</span>
          <span className="analytics-bar-track"><span className="analytics-bar-fill" style={{ width: `${(point.value / maximum) * 100}%` }} /></span>
          <span className="analytics-bar-value">{point.value.toLocaleString()}</span>
        </div>)}
      </div>}
  </section>;
}

export default function AnalyticsPage() {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const requestSequence = useRef(0);

  const load = useCallback(async () => {
    const requestId = ++requestSequence.current;
    setLoading(true);
    setError(null);
    try {
      const [overview, trends, taskCompletion] = await Promise.all([
        analyticsApi.getOverview(), analyticsApi.getTrends(), analyticsApi.getTaskCompletionTrends(),
      ]);
      if (requestId === requestSequence.current) setData({ overview, trends, taskCompletion });
    } catch (reason) {
      if (requestId === requestSequence.current) setError(errorMessage(reason));
    } finally {
      if (requestId === requestSequence.current) setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); return () => { requestSequence.current += 1; }; }, [load, refresh]);

  if (loading && !data) return <section className="analytics-page" aria-busy="true"><p role="status">Loading analytics…</p></section>;
  if (error && !data) return <section className="analytics-page" aria-labelledby="analytics-title">
    <div className="analytics-heading"><div><p className="eyebrow">Workspace</p><h1 id="analytics-title">Analytics</h1></div></div>
    <div className="dashboard-message dashboard-error" role="alert"><p>{error}</p><button className="button button-primary" type="button" onClick={() => setRefresh((value) => value + 1)}>Retry</button></div>
  </section>;
  if (!data) return null;

  const topics = new Map<string, number>();
  data.trends.topic_trends.forEach((week) => week.topics.forEach(({ topic, count }) => topics.set(topic, (topics.get(topic) ?? 0) + count)));
  const topicPoints = [...topics].map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value || a.label.localeCompare(b.label));
  const taskStatusPoints = [
    { label: "Open (including in progress)", value: data.overview.open_tasks },
    { label: "Completed", value: data.overview.completed_tasks },
  ];

  return <section className="analytics-page" aria-labelledby="analytics-title">
    <div className="analytics-heading"><div><p className="eyebrow">Workspace</p><h1 id="analytics-title">Analytics</h1><p className="muted">Persisted meeting, decision, task, and summary-topic data.</p></div>
      <button className="button button-quiet" type="button" onClick={() => setRefresh((value) => value + 1)} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>
    </div>
    {error && <div className="dashboard-message dashboard-error" role="alert"><p>{error}</p><button className="button button-primary" type="button" onClick={() => setRefresh((value) => value + 1)}>Retry</button></div>}
    {loading && <p className="analytics-refresh-status" role="status">Refreshing analytics…</p>}
    <div className="analytics-grid">
      <BarChart title="Meetings per week" description="Meetings by scheduled date, grouped into UTC calendar weeks. Zero-count weeks are included." points={data.overview.meetings_per_week.map(({ week_start, count }) => ({ label: weekLabel(week_start), fullDate: week_start, value: count }))} emptyMessage="No meeting activity in the returned weekly window." />
      <section className="analytics-panel" aria-labelledby="analytics-tasks-completed-over-time">
        <h2 id="analytics-tasks-completed-over-time">Tasks completed over time</h2>
        <p className="analytics-description">Historical completion events are not currently recorded, so a time series cannot be calculated.</p>
        <p className="analytics-unavailable">Unavailable: {data.taskCompletion.reason}</p>
      </section>
      <BarChart title="Open versus completed tasks" description="Current task status snapshot; open includes open and in-progress tasks. This is not a historical trend." points={taskStatusPoints} emptyMessage="No open or completed tasks are currently recorded." />
      <BarChart title="Decisions over time" description="Persisted decisions by creation date, grouped into UTC calendar weeks." points={data.trends.decision_trends.map(({ week_start, count }) => ({ label: weekLabel(week_start), fullDate: week_start, value: count }))} emptyMessage="No decisions in the returned weekly window." />
      <BarChart title="Recurring topics" description="Exact normalized topic strings listed in each meeting’s latest persisted summary. Values sum meeting-topic occurrences across the returned weeks; topics are not semantically clustered." points={topicPoints} emptyMessage="No persisted summary topics in the returned weekly window." />
    </div>
  </section>;
}
