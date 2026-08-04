import { CameraTile } from "@nightwatch/design-system";

const onlineCamera = {
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
};

const offlineCamera = {
  ...onlineCamera,
  id: "cam-2",
  name: "Backyard",
  status: "offline",
};

export function Online() {
  return (
    <div className="w-72">
      <CameraTile camera={onlineCamera} lastEventAt={new Date(Date.now() - 1000 * 60 * 4).toISOString()} />
    </div>
  );
}

export function Offline() {
  return (
    <div className="w-72">
      <CameraTile camera={offlineCamera} lastEventAt={new Date(Date.now() - 3600000 * 6).toISOString()} />
    </div>
  );
}
