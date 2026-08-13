import type { Event } from "@/types";

const severityColor: Record<Event["severity"], string> = {
  low: "oklch(79.2% 0.209 151.711)",
  medium: "oklch(82.8% 0.189 84.429)",
  high: "oklch(82.8% 0.189 84.429)",
  critical: "oklch(70.4% 0.191 22.216)",
};

export function ActivityRow({ event, cameraName }: { event: Event; cameraName: string }) {
  const color = severityColor[event.severity];
  return (
    <div className="flex items-center gap-3.5 px-[18px] py-3.5 border-b border-[oklch(19%_0.015_265)] bg-[oklch(12%_0.015_265)]">
      <div
        className="text-[11px] font-bold tracking-wide px-2.5 py-1.5 rounded-full whitespace-nowrap flex-shrink-0"
        style={{ color, backgroundColor: `color-mix(in oklab, ${color} 16%, transparent)` }}
      >
        {event.severity.toUpperCase()}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[13px] text-[oklch(90%_0.005_265)]">{event.description}</div>
        <div className="text-[11.5px] text-[oklch(55%_0.01_265)] mt-0.5">
          {cameraName} · {new Date(event.timestamp).toLocaleString()}
        </div>
      </div>
    </div>
  );
}
