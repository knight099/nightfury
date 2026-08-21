export interface User {
  id: string;
  username: string;
  name: string;
  role: "super_admin" | "owner" | "admin" | "operator" | "viewer";
  org_id: string | null;
  is_active: boolean;
  must_change_password: boolean;
  deleted_at?: string | null;
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
  deleted_at?: string | null;
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
  step_sequence: StepSequenceStep[];
  sensitivity: "low" | "medium" | "high";
  status: "online" | "offline" | "error";
  last_frame_at: string | null;
  worker_id: string | null;
  idle_fps: number;
  active_fps: number;
  created_at: string;
  deleted_at?: string | null;
}

export interface DetectionZone {
  name: string;
  points: number[][];
}

export interface StepSequenceStep {
  name: string;
  zone: string;
  pose: "standing" | "bending" | "crouching" | "sitting" | "reaching" | null;
  max_seconds: number | null;
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
  /** Operational state — "did somebody deal with it?". Independent of `feedback`. */
  status: "new" | "acknowledged" | "resolved" | "dismissed";
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
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
  deleted_at?: string | null;
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

export interface EventStatsTimeBucket {
  bucket: string;
  count: number;
  by_severity: Record<string, number>;
}

export interface EventStatsCameraBreakdown {
  camera_id: string | null;
  camera_name: string;
  count: number;
}

export interface EventStats {
  total_events: number;
  by_type: Record<string, number>;
  by_severity: Record<string, number>;
  feedback_rate: number;
  false_positive_rate: number;
  time_series: EventStatsTimeBucket[];
  by_camera: EventStatsCameraBreakdown[];
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

export interface AlertRuleDraft {
  name: string;
  event_types: string[];
  min_severity: string;
  notify_channels: ("whatsapp" | "email" | "webhook")[];
  notify_contacts?: NotifyContact[];
  webhook_url?: string | null;
  cameras: string[];
}

export interface CompileSequenceMessage {
  role: "user" | "assistant";
  content: string;
}

export interface CompileSequenceResponse {
  conversation_id: string;
  type: "question" | "draft";
  message?: string | null;
  steps: StepSequenceStep[];
  alert_rule: AlertRuleDraft | null;
  warnings: string[];
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

export interface WhatsAppAlertContact {
  id: string;
  number: string;
  enabled: boolean;
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

export interface DiscoveredDevice {
  uuid: string;
  name: string;
  xaddr: string;
}

export interface DiscoverResponse {
  devices: DiscoveredDevice[];
}

export interface PairCodeResponse {
  code: string;
  expires_at: string;
}

// ─── Guided onboarding wizard ────────────────────────────────────────────

export type OnboardingState =
  | "waiting_claim"
  | "paired"
  | "scanning"
  | "cameras_selected"
  | "stream_verified"
  | "zones_saved"
  | "alert_verified"
  | "protected";

export interface OnboardingCameraState {
  camera_id: string;
  name: string;
  status: "online" | "offline" | "error" | "unassigned";
  first_frame_at: string | null;
  snapshot_url: string | null;
  zones_count: number;
  failure_reason: string | null;
}

export interface OnboardingStatusResponse {
  agent_id: string;
  state: OnboardingState;
  agent_online: boolean;
  last_seen_at: string | null;
  discovered_count: number;
  cameras: OnboardingCameraState[];
  verified_camera_count: number;
  failure_reason: string | null;
}

export interface DiscoveredChannel {
  profile_token: string;
  name: string | null;
}

export interface ChannelsResponse {
  xaddr: string | null;
  channels: DiscoveredChannel[];
}

export interface WalkTestResponse {
  passed: boolean;
  event_id: string | null;
  detected_at: string | null;
}

export interface TestNotificationResponse {
  delivered: boolean;
  detail: string;
}

// ─── Fleet (appliance capacity & camera coverage per site) ──────────────────

export interface FleetCamera {
  id: string;
  name: string;
  status: string;
  agent_id: string | null;
  pinned_agent_id: string | null;
  last_frame_at: string | null;
}

export interface FleetAgent {
  id: string;
  machine_id: string;
  status: string;
  version: string | null;
  last_seen_at: string | null;
  capacity_cameras: number | null;
  /** "declared" = estimated from CPU/RAM; "measured" = revised from observed load. */
  capacity_source: string;
  assigned_count: number;
  assignment_version: number;
  /** "ok" | "degraded" | "over_capacity" */
  load_state: string;
  load_reason: string | null;
  /** Heartbeat too old — its capacity does not count toward coverage. */
  is_stale: boolean;
  spare_capacity: number;
  cameras: FleetCamera[];
}

export interface FleetResponse {
  site_id: string;
  site_name: string;
  agents: FleetAgent[];
  /** Cameras nobody is analysing. The number that matters most on this page. */
  unassigned_cameras: FleetCamera[];
  cameras_total: number;
  cameras_covered: number;
  capacity_total: number;
  capacity_spare: number;
}

// ─── Camera adjacency & journeys ────────────────────────────────────────────
// Adjacency is drawn by an operator, never inferred. A journey correlates
// events across those edges by timing — a plausibility signal, NOT an
// identity claim. No biometrics or appearance matching is involved.

export interface CameraConnection {
  id: string;
  site_id: string;
  camera_a_id: string;
  camera_b_id: string;
  label: string | null;
  created_at: string;
}

export interface JourneyStep {
  camera_id: string;
  camera_name: string;
  event_id: string;
  timestamp: string;
  event_type: string;
  severity: string;
  /** Operator's label for the connection walked to reach this step. */
  via: string | null;
}

export interface Journey {
  seed_event_id: string;
  /** False for most events — nothing happened on a connected camera. Normal. */
  has_journey: boolean;
  summary: string;
  steps: JourneyStep[];
}

// ─── Agentic camera setup ───────────────────────────────────────────────────

export interface SetupProposal {
  id: string;
  camera_id: string;
  status: "pending" | "proposed" | "needs_input" | "failed" | "approved" | "rejected";
  scene_type: string | null;
  scene_description: string | null;
  confidence: number | null;
  proposal: Record<string, unknown>;
  /** Why the agent chose this. Shown verbatim — never summarised. */
  rationale: string | null;
  error: string | null;
  approved_at: string | null;
}

export interface SetupReviewGroup {
  scene_type: string;
  label: string;
  /** False for "needs your input" and for a group of one. */
  bulk_approvable: boolean;
  shared_config: Record<string, unknown>;
  proposals: SetupProposal[];
  differing: SetupProposal[];
}

export interface SetupRun {
  id: string;
  site_id: string;
  status: string;
  camera_count: number;
  pending: number;
  groups: SetupReviewGroup[];
}

/** List-view shape for GET /api/sites/{site_id}/setup-runs — no groups. */
export interface SetupRunSummary {
  id: string;
  site_id: string;
  status: string;
  camera_count: number;
  pending: number;
  created_at: string;
}
