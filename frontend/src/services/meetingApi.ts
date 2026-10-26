import { apiClient } from "../utils/apiClient";

export type MeetingStatus = "pending" | "processing" | "ready" | "failed";
export type ProcessingStatus = "queued" | "running" | "completed" | "partial" | "failed";

export interface MeetingListItem {
  id: string;
  title: string;
  scheduled_at: string | null;
  status: MeetingStatus;
  processing_status: ProcessingStatus | null;
  created_at: string;
  updated_at: string;
}

export interface MeetingListResponse {
  items: MeetingListItem[];
  pagination: { page: number; page_size: number; total: number; total_pages: number };
}

export const meetingApi = {
  list: (page = 1, pageSize = 20) =>
    apiClient.get<MeetingListResponse>(`meetings?page=${page}&page_size=${pageSize}`),
  getById: async (_id: string): Promise<unknown> => {
    throw new Error("Not implemented");
  },
};
