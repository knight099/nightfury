import { SeverityBadge } from "@nightwatch/design-system";

export function AllSeverities() {
  return (
    <div className="flex flex-wrap gap-2">
      <SeverityBadge severity="low" />
      <SeverityBadge severity="medium" />
      <SeverityBadge severity="high" />
      <SeverityBadge severity="critical" />
    </div>
  );
}
