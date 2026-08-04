import { DigestCard } from "@nightwatch/design-system";

const morningDigest = {
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
      "Overnight was mostly quiet. A visitor approached the front gate around 2:40 AM and left after checking the door. No other activity worth flagging.",
    highlights: [{ time: "02:40", camera_name: "Front Gate", why_notable: "Unfamiliar visitor at the gate" }],
    quiet_periods: ["23:00–02:30", "03:00–06:00"],
  },
  delivered_channels: ["whatsapp", "email"],
  created_at: new Date().toISOString(),
};

const degradedDigest = {
  ...morningDigest,
  id: "digest-2",
  payload: {
    ...morningDigest.payload,
    headline: "Evening recap (limited)",
    degraded: true,
    narrative: "We couldn't generate a full summary this time — showing event counts only.",
  },
  delivered_channels: ["email"],
};

export function Default() {
  return (
    <div className="w-96">
      <DigestCard digest={morningDigest} />
    </div>
  );
}

export function Degraded() {
  return (
    <div className="w-96">
      <DigestCard digest={degradedDigest} />
    </div>
  );
}
