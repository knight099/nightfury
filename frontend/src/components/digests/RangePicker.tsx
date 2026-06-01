"use client";

import { useState } from "react";

export interface Range {
  start: Date;
  end: Date;
}

export function presetRanges(): Record<string, () => Range> {
  const now = new Date();
  return {
    "Last night": () => {
      const end = new Date(now);
      end.setHours(7, 0, 0, 0);
      const start = new Date(end);
      start.setDate(start.getDate() - 1);
      start.setHours(22, 0, 0, 0);
      return { start, end };
    },
    Today: () => {
      const start = new Date(now);
      start.setHours(7, 0, 0, 0);
      return { start, end: now };
    },
    "This week": () => {
      const start = new Date(now);
      start.setDate(start.getDate() - 7);
      return { start, end: now };
    },
  };
}

export function RangePicker({ onRange }: { onRange: (r: Range) => void }) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const presets = presetRanges();

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {Object.entries(presets).map(([label, fn]) => (
          <button
            key={label}
            onClick={() => onRange(fn())}
            className="rounded-md border border-[#2A2A2A] bg-[#1A1A1A] px-3 py-1.5 text-sm text-[#F5F5F5] hover:border-[#1E90FF] transition-colors"
          >
            {label}
          </button>
        ))}
      </div>
      <div className="flex gap-2 items-end flex-wrap">
        <label className="flex flex-col text-xs text-[#A3A3A3]">
          Start
          <input
            type="datetime-local"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="mt-1 rounded-md border border-[#2A2A2A] bg-[#1F1F1F] px-2 py-1 text-sm text-[#F5F5F5] focus:border-[#1E90FF] outline-none"
          />
        </label>
        <label className="flex flex-col text-xs text-[#A3A3A3]">
          End
          <input
            type="datetime-local"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="mt-1 rounded-md border border-[#2A2A2A] bg-[#1F1F1F] px-2 py-1 text-sm text-[#F5F5F5] focus:border-[#1E90FF] outline-none"
          />
        </label>
        <button
          disabled={!start || !end}
          onClick={() =>
            onRange({ start: new Date(start), end: new Date(end) })
          }
          className="rounded-md bg-[#1E90FF] px-3 py-1.5 text-sm text-white hover:bg-[#3BA0FF] disabled:opacity-50 transition-colors"
        >
          Generate
        </button>
      </div>
    </div>
  );
}
