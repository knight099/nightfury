"use client";
import { useEffect } from "react";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error("[GlobalError]", error);
  }, [error]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0D0D0D] text-[#F5F5F5] p-6">
      <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-8 max-w-md w-full text-center">
        <h1 className="text-xl font-semibold mb-2">Something went wrong</h1>
        <p className="text-sm text-[#A3A3A3] mb-6">An unexpected error occurred. Try again, or reload the page.</p>
        <div className="flex gap-3 justify-center">
          <button onClick={reset} className="px-4 py-2 rounded bg-[#1E90FF] text-white text-sm font-medium hover:opacity-90">Try again</button>
          <button onClick={() => window.location.reload()} className="px-4 py-2 rounded border border-[#2A2A2A] text-sm hover:bg-[#1F1F1F]">Reload</button>
        </div>
        {process.env.NODE_ENV !== "production" && (
          <pre className="mt-6 text-xs text-left text-[#666666] overflow-auto max-h-40 whitespace-pre-wrap">{error.message}</pre>
        )}
      </div>
    </div>
  );
}
