/**
 * Purpose: TypeScript types for meeting domain entities.
 * Future responsibilities: Align with gateway OpenAPI / shared models.
 * Service ownership: Frontend.
 */

// TODO: Define Meeting, MeetingStatus, Transcript types

export type MeetingStatus = "pending" | "processing" | "ready" | "failed";

export interface Meeting {
  id: string;
  title: string;
  status: MeetingStatus;
  createdAt: string;
}
