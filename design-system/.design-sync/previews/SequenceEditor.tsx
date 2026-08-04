import { SequenceEditor } from "@nightwatch/design-system";

const cameraWithSequence = {
  id: "cam-3",
  org_id: "org-1",
  site_id: "site-1",
  name: "Checkout Counter",
  ingest_mode: "rtsp_pull",
  stream_key: null,
  enabled_events: ["person"],
  detection_zones: [
    { name: "Counter", points: [[0.1, 0.5], [0.9, 0.5], [0.9, 0.95], [0.1, 0.95]] },
    { name: "Exit", points: [[0.0, 0.0], [0.2, 0.0], [0.2, 1.0], [0.0, 1.0]] },
  ],
  step_sequence: [
    { name: "Approaches counter", zone: "Counter", pose: "standing", max_seconds: null },
    { name: "Leaves without paying", zone: "Exit", pose: null, max_seconds: 15 },
  ],
  sensitivity: "medium",
  status: "online",
  last_frame_at: new Date().toISOString(),
  worker_id: "worker-1",
  idle_fps: 1,
  active_fps: 5,
  created_at: new Date(Date.now() - 86400000 * 10).toISOString(),
};

export function Default() {
  return <SequenceEditor camera={cameraWithSequence} onClose={() => {}} />;
}
