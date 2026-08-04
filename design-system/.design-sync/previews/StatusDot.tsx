import { StatusDot } from "@nightwatch/design-system";

export function AllStatuses() {
  return (
    <div className="flex flex-col gap-2 text-xs text-[#A3A3A3]">
      <div className="flex items-center gap-2">
        <StatusDot status="online" /> Front Gate — online
      </div>
      <div className="flex items-center gap-2">
        <StatusDot status="offline" /> Backyard — offline
      </div>
      <div className="flex items-center gap-2">
        <StatusDot status="error" /> Loading Dock — error
      </div>
    </div>
  );
}
