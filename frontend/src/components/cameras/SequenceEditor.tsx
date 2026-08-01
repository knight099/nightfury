"use client";

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Camera, StepSequenceStep } from "@/types";

const POSE_OPTIONS: { value: StepSequenceStep["pose"]; label: string }[] = [
  { value: null, label: "any" },
  { value: "standing", label: "standing" },
  { value: "bending", label: "bending" },
  { value: "crouching", label: "crouching" },
  { value: "sitting", label: "sitting" },
  { value: "reaching", label: "reaching" },
];

export function SequenceEditor({ camera, onClose }: { camera: Camera; onClose: () => void }) {
  const queryClient = useQueryClient();
  const zoneNames = camera.detection_zones.map((z) => z.name);

  const [steps, setSteps] = useState<StepSequenceStep[]>(
    () => (camera.step_sequence || []).map((s) => ({ ...s }))
  );
  const [saveError, setSaveError] = useState<string | null>(null);

  const dirty = useMemo(
    () => JSON.stringify(steps) !== JSON.stringify(camera.step_sequence || []),
    [steps, camera.step_sequence]
  );

  const validationError = useMemo(() => {
    if (steps.length === 0) return null;
    for (const [i, step] of steps.entries()) {
      if (!step.name.trim()) return `Step ${i + 1} needs a name.`;
      if (!zoneNames.includes(step.zone)) return `Step ${i + 1}: zone "${step.zone}" doesn't exist. Draw it in Edit Zones first.`;
    }
    return null;
  }, [steps, zoneNames]);

  const saveMutation = useMutation({
    mutationFn: () => api.updateCamera(camera.id, { step_sequence: steps }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cameras"] });
      onClose();
    },
    onError: (err: Error) => setSaveError(err.message),
  });

  const addStep = () => {
    setSteps([...steps, { name: `Step ${steps.length + 1}`, zone: zoneNames[0] || "", pose: null, max_seconds: null }]);
  };

  const removeStep = (index: number) => {
    setSteps(steps.filter((_, i) => i !== index));
  };

  const moveStep = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= steps.length) return;
    const next = [...steps];
    [next[index], next[target]] = [next[target], next[index]];
    setSteps(next);
  };

  const updateStep = (index: number, patch: Partial<StepSequenceStep>) => {
    setSteps(steps.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  };

  const onBackdropClick = () => {
    if (dirty) {
      if (window.confirm("Discard unsaved sequence changes?")) onClose();
    } else {
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: "rgba(0,0,0,0.7)" }}
      onClick={onBackdropClick}
    >
      <div
        className="bg-[#111111] border border-[#2A2A2A] rounded-lg w-[95vw] max-w-[800px] max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#2A2A2A]">
          <h2 className="text-sm font-medium">Step Sequence — {camera.name}</h2>
          <button onClick={onBackdropClick} className="text-[#A3A3A3] hover:text-[#F5F5F5] text-lg leading-none" aria-label="Close">
            ×
          </button>
        </div>

        <div className="p-4 space-y-3 overflow-auto">
          {zoneNames.length === 0 && (
            <div className="text-xs text-[#666666]">No zones defined yet — draw zones first via "Edit Zones", then steps can reference them.</div>
          )}

          {steps.map((step, i) => (
            <div key={i} className="bg-[#1A1A1A] border border-[#2A2A2A] rounded p-3 space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-[#666666] w-5">{i + 1}.</span>
                <input
                  value={step.name}
                  onChange={(e) => updateStep(i, { name: e.target.value })}
                  placeholder="Step name"
                  className="flex-1 px-2 py-1 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-xs focus:border-[#1E90FF] outline-none"
                />
                <button onClick={() => moveStep(i, -1)} disabled={i === 0} className="text-[#A3A3A3] hover:text-[#F5F5F5] disabled:opacity-30 text-xs px-1">↑</button>
                <button onClick={() => moveStep(i, 1)} disabled={i === steps.length - 1} className="text-[#A3A3A3] hover:text-[#F5F5F5] disabled:opacity-30 text-xs px-1">↓</button>
                <button onClick={() => removeStep(i)} className="text-[#A3A3A3] hover:text-red-400 text-xs px-1">Delete</button>
              </div>
              <div className="flex flex-wrap gap-2">
                <select
                  value={step.zone}
                  onChange={(e) => updateStep(i, { zone: e.target.value })}
                  className="px-2 py-1 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-xs focus:border-[#1E90FF] outline-none"
                >
                  {zoneNames.length === 0 && <option value="">no zones</option>}
                  {zoneNames.map((z) => (
                    <option key={z} value={z}>{z}</option>
                  ))}
                </select>
                <select
                  value={step.pose ?? ""}
                  onChange={(e) => updateStep(i, { pose: (e.target.value || null) as StepSequenceStep["pose"] })}
                  className="px-2 py-1 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-xs focus:border-[#1E90FF] outline-none"
                >
                  {POSE_OPTIONS.map((opt) => (
                    <option key={opt.label} value={opt.value ?? ""}>{opt.label}</option>
                  ))}
                </select>
                <input
                  type="number"
                  min={1}
                  value={step.max_seconds ?? ""}
                  onChange={(e) => updateStep(i, { max_seconds: e.target.value ? Number(e.target.value) : null })}
                  placeholder="max seconds (optional)"
                  className="w-40 px-2 py-1 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-xs focus:border-[#1E90FF] outline-none"
                />
              </div>
            </div>
          ))}

          <button
            onClick={addStep}
            className="px-3 py-1.5 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded text-xs hover:text-[#F5F5F5] transition-colors"
          >
            + Add Step
          </button>

          {validationError && <div className="text-xs text-red-400">{validationError}</div>}
          {saveError && <div className="text-xs text-red-400">Save failed: {saveError}</div>}

          <div className="flex justify-end gap-2 pt-2">
            <button
              onClick={() => {
                setSaveError(null);
                saveMutation.mutate();
              }}
              disabled={!dirty || !!validationError || saveMutation.isPending}
              className="px-3 py-1.5 bg-[#1E90FF] text-white rounded text-xs hover:bg-[#3BA0FF] transition-colors disabled:opacity-50"
            >
              {saveMutation.isPending ? "Saving..." : "Save Sequence"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
