import { cn } from "@/lib/utils";

const statusColors = {
  online: "bg-green-400",
  offline: "bg-gray-500",
  error: "bg-red-400",
  // A camera nobody is analysing. Deliberately NOT gray: "offline" means the
  // camera is down, which the customer can see for themselves. "Unassigned"
  // means the camera is fine and we are not watching it — a coverage gap they
  // did not ask for, and the one state on this page that must not look calm.
  unassigned: "bg-amber-400",
  pending: "bg-gray-500",
};

export function StatusDot({ status }: { status: string }) {
  const color = statusColors[status as keyof typeof statusColors] || statusColors.offline;
  return (
    <span className={cn("inline-block w-2 h-2 rounded-full", color)} />
  );
}
