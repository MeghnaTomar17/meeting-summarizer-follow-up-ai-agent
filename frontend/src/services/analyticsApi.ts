import { apiClient } from "../utils/apiClient";

export interface AnalyticsOverview {
  total_meetings: number;
  meetings_per_week: WeeklyMeetingCount[];
  open_tasks: number;
  completed_tasks: number;
  decisions: number;
}

export interface WeeklyMeetingCount {
  week_start: string;
  count: number;
}

export interface WeeklyDecisionCount {
  week_start: string;
  count: number;
}

export interface TopicTrendCount {
  topic: string;
  count: number;
}

export interface WeeklyTopicTrend {
  week_start: string;
  topics: TopicTrendCount[];
}

export interface AnalyticsTrends {
  decision_trends: WeeklyDecisionCount[];
  meeting_frequency: WeeklyMeetingCount[];
  topic_trends: WeeklyTopicTrend[];
}

export interface TaskCompletionTrends {
  available: false;
  reason: string;
}

export interface UpcomingFollowup {
  id: string;
  meeting_id: string;
  subject: string;
  scheduled_at: string;
  status: "scheduled";
}

export interface PaginatedUpcomingFollowups {
  items: UpcomingFollowup[];
  pagination: { page: number; page_size: number; total: number; total_pages: number };
}

export const analyticsApi = {
  getOverview: () => apiClient.get<AnalyticsOverview>("analytics/overview"),
  getTrends: () => apiClient.get<AnalyticsTrends>("analytics/trends"),
  getTaskCompletionTrends: () => apiClient.get<TaskCompletionTrends>("analytics/task-completion-trends"),
  getUpcomingFollowups: () =>
    apiClient.get<PaginatedUpcomingFollowups>("analytics/upcoming-followups?page=1&page_size=5"),
};
