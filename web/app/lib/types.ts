/* Shared types mirroring the FastAPI Pydantic schemas. */

export type UserRole = "admin" | "assignee";
export type CandidateType = "task" | "request" | "reminder" | "idea" | "knowledge";
export type Priority = "critical" | "high" | "medium" | "low";
export type CandidateStatus =
  | "new" | "needs_review" | "edited" | "approved" | "rejected" | "duplicate" | "error";
export type WorkItemStatus =
  | "inbox" | "backlog" | "ready" | "in_progress" | "blocked" | "review" | "done" | "cancelled" | "archived";

export interface User {
  id: number;
  email: string;
  display_name: string | null;
  role: UserRole;
}

export interface Candidate {
  id: number;
  candidate_type: CandidateType;
  title: string | null;
  summary: string | null;
  priority: Priority | null;
  due_date: string | null;
  status: CandidateStatus;
  task_confidence: number | null;
  missing_fields: string[] | null;
  created_at: string;
}

export interface CandidateMessage {
  message_id: number;
  role: string;
  external_message_id: number;
  sender: string | null;
  sent_at: string | null;
  text: string | null;
}

export interface CandidateDetail {
  candidate: Candidate;
  assignees: { assignee_id: number; is_primary: boolean }[];
  messages: CandidateMessage[];
}

export interface WorkItem {
  id: number;
  type: CandidateType;
  title: string | null;
  summary: string | null;
  priority: Priority | null;
  due_date: string | null;
  status: WorkItemStatus;
  source_candidate_id: number;
}

export interface Board {
  columns: Record<WorkItemStatus, WorkItem[]>;
}

export interface Assignee {
  id: number;
  display_name: string | null;
  telegram_user_id: number | null;
  telegram_username: string | null;
  aliases: string[] | null;
  is_active: boolean;
  user_id: number | null;
}

export interface SyncRun {
  id: number;
  trigger_type: string;
  status: string;
  messages_read: number | null;
  messages_saved: number | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface SyncStatus {
  queue_length: number;
  latest_run: SyncRun | null;
  states: {
    chat_id: number;
    last_external_message_id: number | null;
    last_successful_sync_at: string | null;
    last_error: string | null;
  }[];
}
