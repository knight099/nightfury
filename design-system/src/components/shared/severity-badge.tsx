import { cn } from "@/lib/utils";

const severityColors = {
  low: "bg-green-500/10 text-green-400 border-green-500/20",
  medium: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  high: "bg-orange-500/10 text-orange-400 border-orange-500/20",
  critical: "bg-red-500/10 text-red-400 border-red-500/20",
};

export function SeverityBadge({ severity }: { severity: string }) {
  const colors = severityColors[severity as keyof typeof severityColors] || severityColors.low;
  return (
    <span className={cn("px-2 py-0.5 text-xs font-medium rounded-full border", colors)}>
      {severity.toUpperCase()}
    </span>
  );
}
