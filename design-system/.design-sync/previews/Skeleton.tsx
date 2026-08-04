import { Skeleton } from "@nightwatch/design-system";

export function Default() {
  return <Skeleton className="h-4 w-32" />;
}

export function ContentPlaceholder() {
  return (
    <div className="w-64 space-y-2">
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-5/6" />
      <Skeleton className="h-4 w-2/3" />
    </div>
  );
}

export function CardPlaceholder() {
  return (
    <div className="w-72 space-y-3 rounded-lg border border-[#2A2A2A] bg-[#111111] p-4">
      <Skeleton className="h-3 w-24" />
      <Skeleton className="h-24 w-full rounded-md" />
    </div>
  );
}
