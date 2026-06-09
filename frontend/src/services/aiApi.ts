/**
 * Purpose: HTTP client for AI-related actions (reprocess, follow-up draft).
 * Future responsibilities: Trigger pipelines, fetch AI artifacts.
 * Service ownership: Frontend → gateway-service (proxies ai-service).
 */

// TODO: Implement aiApi

export const aiApi = {
  requestSummary: async (_meetingId: string): Promise<void> => {
    throw new Error("Not implemented");
  },
  getFollowupDraft: async (_meetingId: string): Promise<unknown> => {
    throw new Error("Not implemented");
  },
};
