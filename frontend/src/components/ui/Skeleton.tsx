export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse bg-[#1F1F1F] rounded ${className}`} />;
}
