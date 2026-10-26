import { apiClient } from "../utils/apiClient";

export interface AnalyticsOverview {
  total_meetings: number;
  open_tasks: number;
  completed_tasks: number;
  decisions: number;
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
  getUpcomingFollowups: () =>
    apiClient.get<PaginatedUpcomingFollowups>("analytics/upcoming-followups?page=1&page_size=5"),
};
