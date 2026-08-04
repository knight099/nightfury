import { WebRTCPlayer } from "@nightwatch/design-system";

// Live-only component — it opens a real RTCPeerConnection against the
// backend's signaling endpoint. There's no static, meaningful visual state
// to compose without a live camera on the other end (see NOTES.md).
export function Default() {
  return (
    <div className="flex h-40 w-72 items-center justify-center rounded-lg border border-[#2A2A2A] bg-[#0D0D0D]">
      <WebRTCPlayer cameraId="cam-1" className="h-full w-full object-cover" onError={() => {}} />
    </div>
  );
}
