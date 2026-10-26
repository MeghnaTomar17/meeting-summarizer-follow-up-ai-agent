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

export interface MeetingDetails extends Omit<MeetingListItem, "processing_status"> {
  description: string | null;
  participants: string[];
}
export interface TranscriptSegment { index: number; speaker: string | null; text: string; start_ms: number | null; end_ms: number | null }
export interface TranscriptRecord { id: string; meeting_id: string; segments: TranscriptSegment[]; language: string; created_at: string; updated_at: string }
export interface SummaryRecord { id: string; meeting_id: string; content: string; key_topics: string[]; model_provider: string | null; model_name: string | null; version: number; created_at: string }
export interface TaskRecord { id: string; meeting_id: string; title: string; description: string | null; assignee_id: string | null; due_at: string | null; status: "open" | "in_progress" | "done" | "cancelled"; created_at: string; updated_at: string }
export interface DecisionRecord { id: string; meeting_id: string; statement: string; context: string | null; participants: string[]; created_at: string }
export interface InsightRecord { id: string; meeting_id: string; category: string; title: string; description: string; created_at: string }
export interface FollowupRecord { id: string; meeting_id: string; subject: string; body_html: string; recipients: string[]; status: "draft" | "scheduled" | "sent" | "failed"; scheduled_at: string | null; sent_at: string | null; created_at: string }
export interface Page<T> { items: T[]; pagination: { page: number; page_size: number; total: number; total_pages: number } }
type JobStatus = "queued" | "running" | "completed" | "partial" | "failed";
export interface MeetingProcessingStatus { meeting_id: string; status: JobStatus | null; updated_at: string | null; completed_at: string | null }

export interface MeetingCreateInput { organization_id: string; title: string; description?: string; scheduled_at?: string; participants: string[] }
export interface TranscriptInput { language: string; segments: TranscriptSegment[] }

export const meetingApi = {
  list: (page = 1, pageSize = 20) =>
    apiClient.get<MeetingListResponse>(`meetings?page=${page}&page_size=${pageSize}`),
  getById: (id: string) => apiClient.get<MeetingDetails>(`meetings/${encodeURIComponent(id)}`),
  getTranscript: (id: string) => apiClient.get<TranscriptRecord>(`meetings/${encodeURIComponent(id)}/transcript`),
  getSummary: (id: string) => apiClient.get<SummaryRecord>(`meetings/${encodeURIComponent(id)}/summaries/latest`),
  listTasks: (id: string) => apiClient.get<Page<TaskRecord>>(`meetings/${encodeURIComponent(id)}/tasks`),
  listDecisions: (id: string) => apiClient.get<Page<DecisionRecord>>(`meetings/${encodeURIComponent(id)}/decisions`),
  listInsights: (id: string) => apiClient.get<Page<InsightRecord>>(`meetings/${encodeURIComponent(id)}/insights`),
  listFollowups: (id: string) => apiClient.get<Page<FollowupRecord>>(`meetings/${encodeURIComponent(id)}/followups`),
  getProcessingStatus: (id: string) => apiClient.get<MeetingProcessingStatus>(`meetings/${encodeURIComponent(id)}/processing-status`),
  create: (input: MeetingCreateInput) => apiClient.post<MeetingDetails>("meetings", input),
  createTranscript: (id: string, input: TranscriptInput) => apiClient.post<TranscriptRecord>(`meetings/${encodeURIComponent(id)}/transcript`, input),
};
