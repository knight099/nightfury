import { ZonesEditor } from "@nightwatch/design-system";

const cameraWithZones = {
  id: "cam-1",
  org_id: "org-1",
  site_id: "site-1",
  name: "Front Gate",
  ingest_mode: "rtsp_pull",
  stream_key: null,
  enabled_events: ["person", "vehicle"],
  detection_zones: [
    { name: "Driveway", points: [[0.15, 0.3], [0.85, 0.3], [0.95, 0.9], [0.05, 0.9]] },
  ],
  step_sequence: [],
  sensitivity: "medium",
  status: "online",
  last_frame_at: new Date().toISOString(),
  worker_id: "worker-1",
  idle_fps: 1,
  active_fps: 5,
  created_at: new Date(Date.now() - 86400000 * 30).toISOString(),
};

export function Default() {
  return <ZonesEditor camera={cameraWithZones} onClose={() => {}} />;
}
