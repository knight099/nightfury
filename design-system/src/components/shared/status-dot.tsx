import { cn } from "@/lib/utils";

const statusColors = {
  online: "bg-green-400",
  offline: "bg-gray-500",
  error: "bg-red-400",
};

export function StatusDot({ status }: { status: string }) {
  const color = statusColors[status as keyof typeof statusColors] || statusColors.offline;
  return (
    <span className={cn("inline-block w-2 h-2 rounded-full", color)} />
  );
}
