// Shared sample data used by the api/store shims so every preview renders
// non-empty, realistic-looking state instead of blank loading/empty views.
import type {
  AlertRuleDraft,
  Camera,
  ChatMessage,
  Digest,
  DigestPreferences,
  Event,
  EventStats,
  User,
  WhatsAppAlertContact,
} from "../../types";

export const sampleUser: User = {
  id: "user-1",
  username: "priya",
  name: "Priya Nair",
  role: "owner",
  org_id: "org-1",
  is_active: true,
  must_change_password: false,
};

export const sampleCameras: Camera[] = [
  {
    id: "cam-1",
    org_id: "org-1",
    site_id: "site-1",
    name: "Front Gate",
    ingest_mode: "rtsp_pull",
    stream_key: null,
    enabled_events: ["person", "vehicle"],
    detection_zones: [],
    step_sequence: [],
    sensitivity: "medium",
    status: "online",
    last_frame_at: new Date().toISOString(),
    worker_id: "worker-1",
    idle_fps: 1,
    active_fps: 5,
    created_at: new Date(Date.now() - 86400000 * 30).toISOString(),
  },
  {
    id: "cam-2",
    org_id: "org-1",
    site_id: "site-1",
    name: "Backyard",
    ingest_mode: "rtmp_push",
    stream_key: "nw-stream-key",
    enabled_events: ["person", "intrusion"],
    detection_zones: [],
    step_sequence: [],
    sensitivity: "high",
    status: "offline",
    last_frame_at: new Date(Date.now() - 3600000 * 6).toISOString(),
    worker_id: null,
    idle_fps: 1,
    active_fps: 5,
    created_at: new Date(Date.now() - 86400000 * 12).toISOString(),
  },
];

export const sampleEvents: Event[] = [
  {
    id: "evt-1",
    org_id: "org-1",
    camera_id: "cam-1",
    site_id: "site-1",
    timestamp: new Date(Date.now() - 1000 * 60 * 4).toISOString(),
    event_type: "person",
    confidence: 0.94,
    severity: "medium",
    description: "Person walked up to the front gate and left after a minute.",
    bounding_boxes: [],
    snapshot_url: "",
    clip_url: null,
    ai_model: "gemini-2.0-flash",
    feedback: null,
    feedback_label: null,
    feedback_at: null,
    created_at: new Date(Date.now() - 1000 * 60 * 4).toISOString(),
  },
  {
    id: "evt-2",
    org_id: "org-1",
    camera_id: "cam-2",
    site_id: "site-1",
    timestamp: new Date(Date.now() - 1000 * 60 * 40).toISOString(),
    event_type: "intrusion",
    confidence: 0.81,
    severity: "critical",
    description: "Unknown person climbed the backyard fence at night.",
    bounding_boxes: [],
    snapshot_url: "",
    clip_url: null,
    ai_model: "gemini-2.0-flash",
    feedback: "approved",
    feedback_label: null,
    feedback_at: new Date(Date.now() - 1000 * 60 * 38).toISOString(),
    created_at: new Date(Date.now() - 1000 * 60 * 40).toISOString(),
  },
];

export const sampleEventStats: EventStats = {
  total_events: 18,
  by_type: { person: 11, vehicle: 4, intrusion: 3 },
  by_severity: { low: 6, medium: 8, high: 3, critical: 1 },
  feedback_rate: 0.72,
  false_positive_rate: 0.08,
  time_series: Array.from({ length: 12 }).map((_, i) => ({
    bucket: new Date(Date.now() - (11 - i) * 3600000 * 2).toISOString(),
    count: Math.round(2 + 3 * Math.abs(Math.sin(i))),
    by_severity: {},
  })),
  by_camera: [
    { camera_id: "cam-1", camera_name: "Front Gate", count: 11 },
    { camera_id: "cam-2", camera_name: "Backyard", count: 7 },
  ],
};

export const sampleDigest: Digest = {
  id: "digest-1",
  kind: "scheduled_morning",
  range_start: new Date(Date.now() - 86400000).toISOString(),
  range_end: new Date().toISOString(),
  event_count: 9,
  payload: {
    headline: "Quiet night, one gate visit worth a look",
    period: "overnight",
    total_events: 9,
    by_severity: { low: 6, medium: 2, high: 1 },
    narrative:
      "Overnight was mostly quiet. A visitor approached the front gate around 2:40 AM and left after checking the door.",
    highlights: [
      { time: "02:40", camera_name: "Front Gate", why_notable: "Unfamiliar visitor at the gate" },
    ],
    quiet_periods: ["23:00–02:30", "03:00–06:00"],
  },
  delivered_channels: ["whatsapp", "email"],
  created_at: new Date().toISOString(),
};

export const sampleDigestPreferences: DigestPreferences = {
  morning_enabled: true,
  morning_local_time: "07:00",
  evening_enabled: true,
  evening_local_time: "19:00",
  whatsapp_enabled: true,
  email_enabled: false,
};

export const sampleWhatsAppContacts: WhatsAppAlertContact[] = [
  { id: "contact-1", number: "+91 98765 43210", enabled: true },
];

export const sampleChatMessages: ChatMessage[] = [
  {
    id: "msg-1",
    conversation_id: "conv-1",
    role: "user",
    content: "Anything unusual overnight?",
    created_at: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
  },
  {
    id: "msg-2",
    conversation_id: "conv-1",
    role: "assistant",
    content: "One visitor at the front gate around 2:40 AM, otherwise quiet.",
    created_at: new Date(Date.now() - 1000 * 60 * 4).toISOString(),
  },
];

export const sampleAlertRuleDraft: AlertRuleDraft = {
  name: "Front gate at night",
  event_types: ["person", "intrusion"],
  min_severity: "medium",
  notify_channels: ["whatsapp"],
  cameras: ["cam-1"],
};
