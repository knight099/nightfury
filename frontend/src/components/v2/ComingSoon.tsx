export function ComingSoon({ title }: { title: string }) {
  return (
    <div className="max-w-[1040px] mx-auto px-12 py-20 text-center">
      <div className="text-2xl font-bold mb-2">{title}</div>
      <div className="text-sm text-[oklch(58%_0.01_265)]">
        This is coming soon. Nothing to see here yet.
      </div>
    </div>
  );
}
