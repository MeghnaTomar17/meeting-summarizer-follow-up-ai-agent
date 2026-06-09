/**
 * Purpose: HTTP client for meeting CRUD and uploads.
 * Future responsibilities: list, get, create, update, delete, upload.
 * Service ownership: Frontend → gateway-service /meetings.
 */

// TODO: Implement meetingApi

export const meetingApi = {
  list: async (): Promise<unknown[]> => {
    throw new Error("Not implemented");
  },
  getById: async (_id: string): Promise<unknown> => {
    throw new Error("Not implemented");
  },
};
