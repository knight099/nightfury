export interface User {
  id: string;
  username: string;
  name: string;
  role: "super_admin" | "owner" | "admin" | "operator" | "viewer";
  org_id: string | null;
  is_active: boolean;
  must_change_password: boolean;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  plan: string;
  settings: Record<string, unknown>;
  created_at: string;
}

export interface Site {
  id: string;
  org_id: string;
  name: string;
  address: string | null;
  timezone: string;
  created_at: string;
}

export interface Camera {
  id: string;
  org_id: string;
  site_id: string;
  name: string;
  ingest_mode: "rtsp_pull" | "rtmp_push" | "srt_push";
  stream_key: string | null;
  enabled_events: string[];
  detection_zones: DetectionZone[];
  sensitivity: "low" | "medium" | "high";
  status: "online" | "offline" | "error";
  last_frame_at: string | null;
  worker_id: string | null;
  idle_fps: number;
  active_fps: number;
  created_at: string;
}

export interface DetectionZone {
  name: string;
  points: number[][];
}

export interface Event {
  id: string;
  org_id: string;
  camera_id: string;
  site_id: string;
  timestamp: string;
  event_type: string;
  confidence: number;
  severity: "low" | "medium" | "high" | "critical";
  description: string;
  bounding_boxes: BoundingBox[];
  snapshot_url: string;
  clip_url: string | null;
  ai_model: string;
  feedback: "approved" | "rejected" | "reclassified" | null;
  feedback_label: string | null;
  feedback_at: string | null;
  created_at: string;
}

export interface BoundingBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  label: string;
}

export interface AlertRule {
  id: string;
  org_id: string;
  name: string;
  cameras: string[];
  event_types: string[];
  min_severity: string;
  time_window: TimeWindow | null;
  zones: string[];
  notify_channels: string[];
  notify_contacts: NotifyContact[];
  webhook_url: string | null;
  cooldown_seconds: number;
  enabled: boolean;
  created_at: string;
}

export interface TimeWindow {
  start: string;
  end: string;
  days: string[];
}

export interface NotifyContact {
  type: "whatsapp" | "email" | "webhook";
  value: string;
}

export interface EventStats {
  total_events: number;
  by_type: Record<string, number>;
  by_severity: Record<string, number>;
  feedback_rate: number;
  false_positive_rate: number;
}

export interface PaginatedResponse<T> {
  events: T[];
  total: number;
  page: number;
  pages: number;
}

export type DigestKind = "scheduled_morning" | "scheduled_evening" | "on_demand";

export interface DigestHighlight {
  time: string;
  camera_name: string;
  why_notable: string;
  event_id?: string | null;
}

export interface DigestPayload {
  headline: string;
  period: string;
  total_events: number;
  by_severity: Record<string, number>;
  narrative: string;
  highlights: DigestHighlight[];
  quiet_periods: string[];
  degraded?: boolean;
}

export interface Digest {
  id: string;
  kind: DigestKind;
  range_start: string;
  range_end: string;
  event_count: number;
  payload: DigestPayload;
  delivered_channels: string[];
  created_at: string;
}

export interface DigestListResponse {
  items: Digest[];
  total: number;
}

export interface DigestRequest {
  start: string;
  end: string;
  camera_ids?: string[];
  site_id?: string;
}

export interface ChatMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  camera_id?: string | null;
  event_id?: string | null;
  created_at: string;
}

export interface ConversationSummary {
  conversation_id: string;
  last_message_at: string;
  last_content: string;
  camera_id?: string | null;
  event_id?: string | null;
}

export interface DigestPreferences {
  morning_enabled: boolean;
  morning_local_time: string;
  evening_enabled: boolean;
  evening_local_time: string;
  whatsapp_enabled: boolean;
  email_enabled: boolean;
}

export interface AgentSummary {
  id: string;
  org_id: string;
  machine_id: string;
  version: string;
  transport: string;
  status: string;
  last_seen_at: string | null;
  created_at: string;
}

export interface PairCodeResponse {
  code: string;
  expires_at: string;
}
