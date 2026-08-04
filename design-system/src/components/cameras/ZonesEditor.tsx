"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Camera, DetectionZone, Event, PaginatedResponse } from "@/types";

export function ZonesEditor({ camera, onClose }: { camera: Camera; onClose: () => void }) {
  const queryClient = useQueryClient();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const nameInputRef = useRef<HTMLInputElement | null>(null);

  const [zones, setZones] = useState<DetectionZone[]>(
    () => (camera.detection_zones || []).map((z) => ({ name: z.name, points: z.points.map((p) => [...p]) }))
  );
  const [draft, setDraft] = useState<number[][] | null>(null);
  const [pendingName, setPendingName] = useState<string | null>(null);
  const [pendingPoints, setPendingPoints] = useState<number[][] | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [canvasSize, setCanvasSize] = useState<{ w: number; h: number }>({ w: 960, h: 540 });

  const dirty = useMemo(() => {
    return JSON.stringify(zones) !== JSON.stringify(camera.detection_zones || []);
  }, [zones, camera.detection_zones]);

  const { data: latestEvents } = useQuery<PaginatedResponse<Event>>({
    queryKey: ["camera-latest-event", camera.id],
    queryFn: () => api.getEvents({ camera_id: camera.id, per_page: "1" }),
  });
  const snapshotUrl = latestEvents?.events?.[0]?.snapshot_url || null;

  const saveMutation = useMutation({
    mutationFn: () => api.updateCamera(camera.id, { detection_zones: zones }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cameras"] });
      onClose();
    },
    onError: (err: Error) => setSaveError(err.message),
  });

  useEffect(() => {
    const update = () => {
      const el = containerRef.current;
      if (!el) return;
      const w = el.clientWidth;
      const h = Math.round((w * 9) / 16);
      setCanvasSize({ w, h });
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    canvas.width = canvasSize.w;
    canvas.height = canvasSize.h;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const toPx = (p: number[]) => [p[0] * canvas.width, p[1] * canvas.height] as const;

    const drawPolygon = (points: number[][], filled: boolean) => {
      if (points.length === 0) return;
      ctx.beginPath();
      points.forEach((p, i) => {
        const [x, y] = toPx(p);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      if (filled) {
        ctx.closePath();
        ctx.fillStyle = "rgba(30, 144, 255, 0.25)";
        ctx.fill();
      }
      ctx.strokeStyle = "#1E90FF";
      ctx.lineWidth = 2;
      ctx.stroke();
      points.forEach((p) => {
        const [x, y] = toPx(p);
        ctx.beginPath();
        ctx.arc(x, y, 3.5, 0, Math.PI * 2);
        ctx.fillStyle = "#1E90FF";
        ctx.fill();
      });
    };

    zones.forEach((z) => drawPolygon(z.points, true));
    if (draft) drawPolygon(draft, false);
  }, [zones, draft, canvasSize]);

  useEffect(() => {
    if (pendingName !== null && nameInputRef.current) {
      nameInputRef.current.focus();
      nameInputRef.current.select();
    }
  }, [pendingName]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (pendingName !== null) {
          setPendingName(null);
          setPendingPoints(null);
          return;
        }
        if (draft) {
          setDraft(null);
          setErrorMsg(null);
          return;
        }
        if (dirty) {
          if (window.confirm("Discard unsaved zone changes?")) onClose();
        } else {
          onClose();
        }
      } else if (e.key === "Enter" && draft && pendingName === null) {
        finishPolygon();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, dirty, pendingName]);

  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (pendingName !== null) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    const next = [...(draft || []), [x, y]];
    setDraft(next);
    setErrorMsg(null);
  };

  const handleCanvasDoubleClick = () => {
    finishPolygon();
  };

  const finishPolygon = () => {
    if (!draft) return;
    if (draft.length < 3) {
      setErrorMsg("A zone needs at least 3 points.");
      return;
    }
    setPendingPoints(draft);
    setPendingName(`Zone ${zones.length + 1}`);
    setDraft(null);
    setErrorMsg(null);
  };

  const commitPendingName = () => {
    if (pendingPoints === null) return;
    const name = (pendingName || "").trim() || `Zone ${zones.length + 1}`;
    setZones([...zones, { name, points: pendingPoints }]);
    setPendingName(null);
    setPendingPoints(null);
  };

  const cancelPendingName = () => {
    setPendingName(null);
    setPendingPoints(null);
  };

  const startNewZone = () => {
    if (pendingName !== null) return;
    setDraft([]);
    setErrorMsg(null);
  };

  const cancelDraft = () => {
    setDraft(null);
    setErrorMsg(null);
  };

  const undoLastPoint = () => {
    if (!draft || draft.length === 0) return;
    setDraft(draft.slice(0, -1));
  };

  const editZone = (index: number) => {
    if (pendingName !== null) return;
    const z = zones[index];
    setZones(zones.filter((_, i) => i !== index));
    setDraft(z.points.map((p) => [...p]));
    setErrorMsg(null);
  };

  const deleteZone = (index: number) => {
    setZones(zones.filter((_, i) => i !== index));
  };

  const renameZone = (index: number, name: string) => {
    setZones(zones.map((z, i) => (i === index ? { ...z, name } : z)));
  };

  const discardChanges = () => {
    setZones((camera.detection_zones || []).map((z) => ({ name: z.name, points: z.points.map((p) => [...p]) })));
    setDraft(null);
    setPendingName(null);
    setPendingPoints(null);
    setErrorMsg(null);
    setSaveError(null);
  };

  const onBackdropClick = () => {
    if (dirty) {
      if (window.confirm("Discard unsaved zone changes?")) onClose();
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
        className="bg-[#111111] border border-[#2A2A2A] rounded-lg w-[95vw] max-w-[1200px] max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#2A2A2A]">
          <h2 className="text-sm font-medium">Zones — {camera.name}</h2>
          <button
            onClick={onBackdropClick}
            className="text-[#A3A3A3] hover:text-[#F5F5F5] text-lg leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="flex flex-col lg:flex-row gap-4 p-4 overflow-auto">
          <div className="flex-1 min-w-0 space-y-3">
            <div className="flex flex-wrap gap-2">
              <button
                onClick={startNewZone}
                disabled={draft !== null || pendingName !== null}
                className="px-3 py-1.5 bg-[#1E90FF] text-white rounded text-xs hover:bg-[#3BA0FF] transition-colors disabled:opacity-50"
              >
                New Zone
              </button>
              <button
                onClick={finishPolygon}
                disabled={!draft || draft.length < 3}
                className="px-3 py-1.5 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded text-xs hover:text-[#F5F5F5] transition-colors disabled:opacity-40"
              >
                Finish Polygon
              </button>
              <button
                onClick={undoLastPoint}
                disabled={!draft || draft.length === 0}
                className="px-3 py-1.5 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded text-xs hover:text-[#F5F5F5] transition-colors disabled:opacity-40"
              >
                Undo Last Point
              </button>
              <button
                onClick={cancelDraft}
                disabled={!draft}
                className="px-3 py-1.5 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded text-xs hover:text-[#F5F5F5] transition-colors disabled:opacity-40"
              >
                Cancel
              </button>
              <div className="flex-1" />
              <button
                onClick={discardChanges}
                disabled={!dirty || saveMutation.isPending}
                className="px-3 py-1.5 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded text-xs hover:text-[#F5F5F5] transition-colors disabled:opacity-40"
              >
                Discard Changes
              </button>
              <button
                onClick={() => {
                  setSaveError(null);
                  saveMutation.mutate();
                }}
                disabled={!dirty || saveMutation.isPending || pendingName !== null}
                className="px-3 py-1.5 bg-[#1E90FF] text-white rounded text-xs hover:bg-[#3BA0FF] transition-colors disabled:opacity-50"
              >
                {saveMutation.isPending ? "Saving..." : "Save All"}
              </button>
            </div>

            <div
              ref={containerRef}
              className="relative w-full bg-[#111111] border border-[#2A2A2A] rounded overflow-hidden"
              style={{ aspectRatio: "16 / 9" }}
            >
              {snapshotUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={snapshotUrl}
                  alt={`${camera.name} reference`}
                  className="absolute inset-0 w-full h-full object-contain bg-black"
                  draggable={false}
                />
              ) : (
                <div
                  className="absolute inset-0"
                  style={{
                    backgroundColor: "#111111",
                    backgroundImage:
                      "linear-gradient(rgba(255,255,255,0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.1) 1px, transparent 1px)",
                    backgroundSize: "40px 40px",
                  }}
                />
              )}
              <canvas
                ref={canvasRef}
                onClick={handleCanvasClick}
                onDoubleClick={handleCanvasDoubleClick}
                className="absolute inset-0 w-full h-full cursor-crosshair"
                style={{ touchAction: "none" }}
              />
            </div>

            {errorMsg && <div className="text-xs text-red-400">{errorMsg}</div>}
            {saveError && <div className="text-xs text-red-400">Save failed: {saveError}</div>}
          </div>

          <div className="w-full lg:w-72 shrink-0 space-y-3">
            <div className="text-xs text-[#A3A3A3] space-y-1">
              <div className="font-medium text-[#F5F5F5]">How to draw</div>
              <div>1. Click <span className="text-[#F5F5F5]">New Zone</span>.</div>
              <div>2. Click on the image to add polygon points.</div>
              <div>3. Double-click or press Enter to close (≥3 points).</div>
              <div>4. Name the zone, then Save All.</div>
              {!snapshotUrl && (
                <div className="text-[#666666] pt-1">No snapshot yet — draw on the grid; coordinates are stored as fractions and apply to live frames.</div>
              )}
            </div>

            <div className="space-y-2">
              <div className="text-xs font-medium">Zones ({zones.length})</div>
              {zones.length === 0 && pendingName === null && (
                <div className="text-[10px] text-[#666666]">No zones yet.</div>
              )}
              {zones.map((z, i) => (
                <div key={i} className="bg-[#1A1A1A] border border-[#2A2A2A] rounded p-2 space-y-2">
                  <input
                    value={z.name}
                    onChange={(e) => renameZone(i, e.target.value)}
                    className="w-full px-2 py-1 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-xs focus:border-[#1E90FF] outline-none"
                  />
                  <div className="flex items-center justify-between text-[10px] text-[#666666]">
                    <span>{z.points.length} points</span>
                    <div className="flex gap-2">
                      <button
                        onClick={() => editZone(i)}
                        className="text-[#A3A3A3] hover:text-[#1E90FF] transition-colors"
                      >
                        Edit Points
                      </button>
                      <button
                        onClick={() => deleteZone(i)}
                        className="text-[#A3A3A3] hover:text-red-400 transition-colors"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                </div>
              ))}
              {pendingName !== null && (
                <div className="bg-[#1A1A1A] border border-[#1E90FF] rounded p-2 space-y-2">
                  <input
                    ref={nameInputRef}
                    value={pendingName}
                    onChange={(e) => setPendingName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        commitPendingName();
                      } else if (e.key === "Escape") {
                        e.preventDefault();
                        cancelPendingName();
                      }
                    }}
                    placeholder="Zone name"
                    className="w-full px-2 py-1 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-xs focus:border-[#1E90FF] outline-none"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={commitPendingName}
                      className="px-2 py-1 bg-[#1E90FF] text-white rounded text-[10px] hover:bg-[#3BA0FF] transition-colors"
                    >
                      Save Name
                    </button>
                    <button
                      onClick={cancelPendingName}
                      className="px-2 py-1 text-[#A3A3A3] text-[10px] hover:text-[#F5F5F5]"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
