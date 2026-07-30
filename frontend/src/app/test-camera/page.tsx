"use client";

import { useRef, useState, useCallback, useEffect } from "react";
import { api } from "@/lib/api";
import { Camera, Play, Square, Loader2, MapPin, X, Send, Trash2, MessageSquare, Mic, Volume2 } from "lucide-react";

interface DetectedEvent {
  event_type: string;
  confidence: number;
  severity: string;
  description: string;
  bounding_boxes: { x1: number; y1: number; x2: number; y2: number; label: string }[];
}

interface Person {
  description?: string;
  carrying?: string | null;
  carrying_count?: number;
  activity?: string;
  ppe?: { helmet?: boolean; vest?: boolean; gloves?: boolean; mask?: boolean };
}

interface Vehicle {
  type?: string;
  color?: string;
  license_plate?: string | null;
  license_plate_confidence?: number;
  direction?: string;
}

interface AnalysisMeta {
  latency_ms: number;
  prompt_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
}

interface YoloDetection {
  coco_class: string;
  confidence: number;
  bbox: { x1: number; y1: number; x2: number; y2: number };
}

interface YoloGateInfo {
  action: "drop" | "escalate" | "fastpath";
  detections: YoloDetection[];
  latency_ms: number;
}

interface AnalysisResult {
  events: DetectedEvent[];
  person_count: number;
  people?: Person[];
  vehicles?: Vehicle[];
  objects?: { boxes?: number; bags?: number; pallets?: number; packages?: number };
  scene_summary: string;
  _meta?: AnalysisMeta;
  decision?: "drop" | "escalate" | "fastpath";
  yolo?: YoloGateInfo;
}

interface AudioEvent {
  event_type: string;
  confidence: number;
  severity: string;
  description: string;
  timestamp_offset_s: number;
}

interface AudioResult {
  events: AudioEvent[];
  speech_detected: boolean;
  speech_summary: string | null;
  ambient_level: string;
  dominant_sound: string;
  scene_summary: string;
  _meta?: AnalysisMeta & { duration_s?: number };
}

interface SceneContext {
  center: string;
  left: string;
  right: string;
  top: string;
  bottom: string;
  background: string;
}

interface CombinedEvent {
  event_type: string;
  confidence: number;
  severity: string;
  source: "visual" | "audio" | "combined";
  description: string;
  bounding_boxes: { x1: number; y1: number; x2: number; y2: number; label: string }[];
}

interface CombinedResult {
  events: CombinedEvent[];
  person_count: number;
  people?: Person[];
  vehicles?: Vehicle[];
  objects?: { boxes?: number; bags?: number; pallets?: number; packages?: number };
  audio: {
    ambient_level: string;
    dominant_sound: string;
    speech_detected: boolean;
    speech_summary: string | null;
  };
  scene_summary: string;
  _meta?: AnalysisMeta & { audio_duration_s?: number };
}

interface EventLogEntry {
  captured_at: string;
  result: AnalysisResult;
  audioResult?: AudioResult;
  combinedResult?: CombinedResult;
}

const SCENE_TYPES = [
  { value: "general_security", label: "General Security" },
  { value: "warehouse", label: "Warehouse" },
  { value: "manufacturing", label: "Manufacturing Plant" },
  { value: "office", label: "Office Space" },
  { value: "drone_aerial", label: "Drone / Aerial" },
];

const EMPTY_CONTEXT: SceneContext = { center: "", left: "", right: "", top: "", bottom: "", background: "" };

async function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = reader.result as string;
      resolve(result.split(",")[1]);
    };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

export default function TestCameraPage() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [streaming, setStreaming] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzingYolo, setAnalyzingYolo] = useState(false);
  const [autoMode, setAutoMode] = useState(false);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState("");
  const autoIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const [sceneType, setSceneType] = useState("general_security");
  const [useContext, setUseContext] = useState(false);
  const [contextEditing, setContextEditing] = useState(false);
  const [sceneContext, setSceneContext] = useState<SceneContext>(EMPTY_CONTEXT);

  const [sessionStats, setSessionStats] = useState({
    calls: 0, prompt_tokens: 0, output_tokens: 0, total_tokens: 0,
    cost_usd: 0, total_latency_ms: 0,
  });
  const [sessionStartedAt] = useState(() => Date.now());
  const [, setNow] = useState(Date.now());

  const [eventLog, setEventLog] = useState<EventLogEntry[]>([]);
  const [chatHistory, setChatHistory] = useState<{ role: "user" | "assistant"; content: string; timestamp: number; meta?: { total_tokens: number; latency_ms: number } }[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const lastFrameRef = useRef<string | null>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);

  // Combined capture state
  const [combinedCapturing, setCombinedCapturing] = useState(false);
  const [combinedCountdown, setCombinedCountdown] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const startCamera = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 1280, height: 720, facingMode: "environment" },
      });
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        setStreaming(true);
        setError("");
      }
    } catch {
      setError("Cannot access camera. Please allow camera permissions.");
    }
  }, []);

  const stopCamera = useCallback(() => {
    if (videoRef.current?.srcObject) {
      const tracks = (videoRef.current.srcObject as MediaStream).getTracks();
      tracks.forEach((t) => t.stop());
      videoRef.current.srcObject = null;
    }
    setStreaming(false);
    setAutoMode(false);
    if (autoIntervalRef.current) {
      clearInterval(autoIntervalRef.current);
      autoIntervalRef.current = null;
    }
  }, []);

  const captureFrame = useCallback((): string | null => {
    if (!videoRef.current || !canvasRef.current) return null;
    const canvas = canvasRef.current;
    canvas.width = 1280;
    canvas.height = 720;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(videoRef.current, 0, 0, 1280, 720);
    const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
    return dataUrl.split(",")[1];
  }, []);

  const buildPayload = useCallback((base64: string) => {
    const payload: Record<string, unknown> = { image_base64: base64, scene_type: sceneType };
    if (useContext) {
      const filtered = Object.fromEntries(Object.entries(sceneContext).filter(([, v]) => v?.trim()));
      if (Object.keys(filtered).length > 0) payload.scene_context = filtered;
    }
    return payload;
  }, [sceneType, useContext, sceneContext]);

  const addSessionStats = useCallback((meta: AnalysisMeta) => {
    setSessionStats((s) => ({
      calls: s.calls + 1,
      prompt_tokens: s.prompt_tokens + meta.prompt_tokens,
      output_tokens: s.output_tokens + meta.output_tokens,
      total_tokens: s.total_tokens + meta.total_tokens,
      cost_usd: s.cost_usd + meta.cost_usd,
      total_latency_ms: s.total_latency_ms + meta.latency_ms,
    }));
  }, []);

  const captureAndAnalyze = useCallback(async () => {
    if (analyzing) return;
    const base64 = captureFrame();
    if (!base64) return;
    lastFrameRef.current = base64;
    setAnalyzing(true);
    setError("");
    try {
      const data = await api.request<AnalysisResult>("/api/test-camera/analyze", {
        method: "POST",
        body: JSON.stringify(buildPayload(base64)),
      });
      setResult(data);
      setEventLog((prev) => [...prev, { captured_at: new Date().toISOString(), result: data }].slice(-10));
      if (data._meta) addSessionStats(data._meta);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  }, [analyzing, captureFrame, buildPayload, addSessionStats]);

  // Runs the frame through the local YOLO gate first (drop / fastpath / escalate),
  // calling Gemini only when the gate escalates — lets you preview the same
  // cost-reduction pipeline the worker uses, on demand.
  const captureAndAnalyzeYolo = useCallback(async () => {
    if (analyzingYolo) return;
    const base64 = captureFrame();
    if (!base64) return;
    lastFrameRef.current = base64;
    setAnalyzingYolo(true);
    setError("");
    try {
      const data = await api.request<AnalysisResult>("/api/test-camera/analyze-yolo-gemini", {
        method: "POST",
        body: JSON.stringify({ image_base64: base64, scene_type: sceneType }),
      });
      setResult(data);
      setEventLog((prev) => [...prev, { captured_at: new Date().toISOString(), result: data }].slice(-10));
      if (data._meta) addSessionStats(data._meta);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setAnalyzingYolo(false);
    }
  }, [analyzingYolo, captureFrame, sceneType, addSessionStats]);

  // Capture frame + 4s audio → single Gemini call → unified events
  const captureWithAudio = useCallback(async () => {
    if (combinedCapturing || !streaming) return;
    setCombinedCapturing(true);
    setError("");

    const imageBase64 = captureFrame();
    if (!imageBase64) { setCombinedCapturing(false); return; }
    lastFrameRef.current = imageBase64;

    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "audio/webm";

    let audioBase64: string | null = null;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream, { mimeType });
      const chunks: Blob[] = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
      await new Promise<void>((resolve) => {
        recorder.onstop = () => resolve();
        recorder.start();
        let secs = 0;
        const t = setInterval(() => {
          secs++;
          setCombinedCountdown(4 - secs);
          if (secs >= 4) { clearInterval(t); recorder.stop(); }
        }, 1000);
        setCombinedCountdown(4);
      });
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunks, { type: mimeType });
      audioBase64 = await blobToBase64(blob);
    } catch {
      // mic denied — fall back to frame-only
    }

    try {
      if (audioBase64) {
        const payload: Record<string, unknown> = {
          image_base64: imageBase64,
          audio_base64: audioBase64,
          audio_mime_type: mimeType.split(";")[0],
          scene_type: sceneType,
          audio_duration_s: 4,
        };
        if (useContext) {
          const filtered = Object.fromEntries(Object.entries(sceneContext).filter(([, v]) => v?.trim()));
          if (Object.keys(filtered).length > 0) payload.scene_context = filtered;
        }
        const data = await api.request<CombinedResult>("/api/test-camera/analyze-combined", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        // Mirror into AnalysisResult shape so the video overlay still works
        const asFrame: AnalysisResult = {
          events: data.events.map((e) => ({
            event_type: e.event_type,
            confidence: e.confidence,
            severity: e.severity,
            description: e.description,
            bounding_boxes: e.bounding_boxes ?? [],
          })),
          person_count: data.person_count,
          people: data.people,
          vehicles: data.vehicles,
          objects: data.objects,
          scene_summary: data.scene_summary,
          _meta: data._meta,
        };
        setResult(asFrame);
        if (data._meta) addSessionStats(data._meta);
        setEventLog((prev) => [...prev, {
          captured_at: new Date().toISOString(),
          result: asFrame,
          combinedResult: data,
        }].slice(-10));
      } else {
        // No mic — plain frame analysis
        const data = await api.request<AnalysisResult>("/api/test-camera/analyze", {
          method: "POST",
          body: JSON.stringify(buildPayload(imageBase64)),
        });
        setResult(data);
        if (data._meta) addSessionStats(data._meta);
        setEventLog((prev) => [...prev, { captured_at: new Date().toISOString(), result: data }].slice(-10));
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Combined capture failed");
    } finally {
      setCombinedCapturing(false);
      setCombinedCountdown(0);
    }
  }, [combinedCapturing, streaming, captureFrame, buildPayload, sceneType, useContext, sceneContext, addSessionStats]);

  const toggleAuto = useCallback(() => {
    if (autoMode) {
      setAutoMode(false);
      if (autoIntervalRef.current) { clearInterval(autoIntervalRef.current); autoIntervalRef.current = null; }
    } else {
      setAutoMode(true);
      captureWithAudio();
      autoIntervalRef.current = setInterval(captureWithAudio, 6000);
    }
  }, [autoMode, captureWithAudio]);

  useEffect(() => {
    return () => {
      if (autoIntervalRef.current) clearInterval(autoIntervalRef.current);
      stopCamera();
    };
  }, [stopCamera]);

  useEffect(() => {
    if (chatScrollRef.current) chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
  }, [chatHistory, eventLog]);

  const sendChat = useCallback(async (question: string, includeImage = false) => {
    if (!question.trim() || chatLoading) return;
    setChatHistory((prev) => [...prev, { role: "user", content: question, timestamp: Date.now() }]);
    setChatInput("");
    setChatLoading(true);
    try {
      const recentEvents = eventLog.map((e) => ({
        captured_at: e.captured_at,
        events: e.result.events,
        person_count: e.result.person_count,
        people: e.result.people,
        vehicles: e.result.vehicles,
        objects: e.result.objects,
        scene_summary: e.result.scene_summary,
      }));
      const payload: Record<string, unknown> = {
        question, recent_events: recentEvents,
        history: chatHistory.map((m) => ({ role: m.role, content: m.content })),
        scene_type: sceneType,
      };
      if (includeImage && lastFrameRef.current) payload.image_base64 = lastFrameRef.current;
      if (useContext) {
        const filtered = Object.fromEntries(Object.entries(sceneContext).filter(([, v]) => v?.trim()));
        if (Object.keys(filtered).length > 0) payload.scene_context = filtered;
      }
      const data = await api.request<{ answer: string; _meta?: AnalysisMeta }>("/api/test-camera/chat", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setChatHistory((prev) => [...prev, {
        role: "assistant", content: data.answer, timestamp: Date.now(),
        meta: data._meta ? { total_tokens: data._meta.total_tokens, latency_ms: data._meta.latency_ms } : undefined,
      }]);
      if (data._meta) addSessionStats(data._meta);
    } catch (err: unknown) {
      setChatHistory((prev) => [...prev, {
        role: "assistant",
        content: "Error: " + (err instanceof Error ? err.message : "Failed to get response"),
        timestamp: Date.now(),
      }]);
    } finally {
      setChatLoading(false);
    }
  }, [eventLog, chatHistory, sceneType, useContext, sceneContext, chatLoading, addSessionStats]);

  const severityColor = (s: string) => {
    switch (s) {
      case "critical": return "text-[#EF4444]";
      case "high": return "text-[#F97316]";
      case "medium": return "text-[#FBBF24]";
      default: return "text-[#4ADE80]";
    }
  };

  const objects = result?.objects || {};
  const totalObjects = (objects.boxes || 0) + (objects.bags || 0) + (objects.pallets || 0) + (objects.packages || 0);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-xl font-bold text-[#F5F5F5]">Test Camera — AI Analysis</h1>
        <div className="flex gap-2 flex-wrap">
          <select
            value={sceneType}
            onChange={(e) => setSceneType(e.target.value)}
            className="px-3 py-1.5 bg-[#1A1A1A] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5] focus:outline-none focus:border-[#1E90FF]"
          >
            {SCENE_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
          <button
            onClick={() => setContextEditing(true)}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm transition-colors ${
              useContext
                ? "bg-[#1E90FF]/20 text-[#1E90FF] border border-[#1E90FF]"
                : "bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] hover:text-[#F5F5F5]"
            }`}
          >
            <MapPin size={14} /> Scene Context {useContext ? "ON" : "OFF"}
          </button>
          {!streaming ? (
            <button
              onClick={startCamera}
              className="flex items-center gap-2 px-3 py-1.5 bg-[#1E90FF] text-white rounded-md text-sm hover:bg-[#3BA0FF] transition-colors"
            >
              <Camera size={16} /> Start Camera
            </button>
          ) : (
            <>
              <button
                onClick={captureAndAnalyze}
                disabled={analyzing || analyzingYolo || combinedCapturing}
                className="flex items-center gap-2 px-3 py-1.5 bg-[#1E90FF] text-white rounded-md text-sm hover:bg-[#3BA0FF] disabled:opacity-50 transition-colors"
              >
                {analyzing ? <Loader2 size={16} className="animate-spin" /> : <Camera size={16} />}
                {analyzing ? "Analyzing..." : "Capture"}
              </button>
              <button
                onClick={captureAndAnalyzeYolo}
                disabled={analyzing || analyzingYolo || combinedCapturing}
                className="flex items-center gap-2 px-3 py-1.5 bg-[#1A1A1A] text-[#4ADE80] border border-[#4ADE80]/50 rounded-md text-sm hover:border-[#4ADE80] disabled:opacity-50 transition-colors"
                title="Run the local YOLO gate first — only calls Gemini if the gate escalates"
              >
                {analyzingYolo ? <Loader2 size={16} className="animate-spin" /> : <Camera size={16} />}
                {analyzingYolo ? "Testing..." : "Capture (YOLO gate)"}
              </button>
              <button
                onClick={captureWithAudio}
                disabled={analyzing || analyzingYolo || combinedCapturing}
                className="flex items-center gap-2 px-3 py-1.5 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded-md text-sm hover:text-[#F5F5F5] hover:border-[#1E90FF] disabled:opacity-50 transition-colors"
                title="Capture frame + 4s audio simultaneously"
              >
                {combinedCapturing
                  ? <><Loader2 size={14} className="animate-spin" /> {combinedCountdown}s</>
                  : <><Camera size={14} /><Mic size={14} /> Capture + Audio</>
                }
              </button>
              <button
                onClick={toggleAuto}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm transition-colors ${
                  autoMode
                    ? "bg-[#4ADE80] text-black"
                    : "bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] hover:text-[#F5F5F5]"
                }`}
              >
                <Play size={16} /> {autoMode ? "Auto ON" : "Auto"}
              </button>
              <button
                onClick={stopCamera}
                className="flex items-center gap-2 px-3 py-1.5 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded-md text-sm hover:text-[#EF4444] transition-colors"
              >
                <Square size={16} /> Stop
              </button>
            </>
          )}
        </div>
      </div>

      {contextEditing && (
        <SceneContextModal
          context={sceneContext}
          onSave={(ctx, enabled) => { setSceneContext(ctx); setUseContext(enabled); setContextEditing(false); }}
          onClose={() => setContextEditing(false)}
        />
      )}

      {error && <p className="text-sm text-red-400 bg-[#111111] border border-[#2A2A2A] rounded-lg p-3">{error}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 space-y-3">
          <div className="relative bg-[#111111] border border-[#2A2A2A] rounded-lg overflow-hidden aspect-video">
            <video ref={videoRef} autoPlay playsInline muted className="w-full h-full object-cover" />
            {!streaming && (
              <div className="absolute inset-0 flex items-center justify-center">
                <p className="text-[#666666] text-sm">Click &quot;Start Camera&quot; to begin</p>
              </div>
            )}
            {(analyzing || analyzingYolo || combinedCapturing) && (
              <div className="absolute top-2 right-2 flex items-center gap-1.5">
                <div className="bg-[#1E90FF] text-white text-xs px-2 py-1 rounded animate-pulse flex items-center gap-1">
                  {combinedCapturing && <Mic size={11} />}
                  {combinedCapturing ? `Recording ${combinedCountdown}s…` : "Analyzing…"}
                </div>
              </div>
            )}
            {result && result.events.length > 0 && (
              <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 1280 720">
                {result.events.flatMap((e) =>
                  e.bounding_boxes.map((bb, i) => (
                    <g key={`${e.event_type}-${i}`}>
                      <rect
                        x={bb.x1} y={bb.y1} width={bb.x2 - bb.x1} height={bb.y2 - bb.y1}
                        fill="none"
                        stroke={e.severity === "critical" ? "#EF4444" : e.severity === "high" ? "#F97316" : "#1E90FF"}
                        strokeWidth="2"
                      />
                      <text x={bb.x1} y={bb.y1 - 4} fill="#F5F5F5" fontSize="14" fontFamily="monospace">
                        {bb.label} ({(e.confidence * 100).toFixed(0)}%)
                      </text>
                    </g>
                  ))
                )}
              </svg>
            )}
          </div>
          <canvas ref={canvasRef} className="hidden" />

          {result?.decision && result.yolo && <YoloGateBadge decision={result.decision} yolo={result.yolo} />}

          {result && (
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
              <StatBox label="Events" value={result.events.length} color={result.events.length > 0 ? "#F97316" : "#666666"} />
              <StatBox label="People" value={result.person_count} />
              <StatBox label="Vehicles" value={result.vehicles?.length || 0} />
              <StatBox label="Objects" value={totalObjects} />
              <StatBox label="Boxes/Bags" value={`${objects.boxes || 0}/${objects.bags || 0}`} />
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-2 text-xs space-y-0.5">
              <div className="flex items-center justify-between">
                <span className="text-[#666666] uppercase text-[10px]">Session</span>
                <a href="/usage" className="text-[10px] text-[#1E90FF] hover:underline">All-time →</a>
              </div>
              <div className="text-[#A3A3A3]">
                <span className="text-[#F5F5F5]">{formatDuration(Date.now() - sessionStartedAt)}</span> · {sessionStats.calls} calls · <span className="text-[#4ADE80]">${sessionStats.cost_usd.toFixed(4)}</span>
              </div>
              <div className="text-[#666666] text-[10px]">{sessionStats.total_tokens.toLocaleString()} tokens · avg {sessionStats.calls ? Math.round(sessionStats.total_latency_ms / sessionStats.calls) : 0}ms</div>
            </div>
            <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-2 text-xs space-y-0.5">
              <span className="text-[#666666] uppercase text-[10px]">Config</span>
              <div className="text-[#A3A3A3]">
                <span className="text-[#1E90FF] capitalize">{sceneType.replace(/_/g, " ")}</span> · Context <span className={useContext ? "text-[#4ADE80]" : "text-[#666666]"}>{useContext ? "ON" : "OFF"}</span>
              </div>
              <div className="text-[#666666] text-[10px]">Gemini 2.5 Flash</div>
            </div>
          </div>
        </div>

        {/* Chat & event log panel */}
        <div className="flex flex-col h-[calc(100vh-180px)] bg-[#111111] border border-[#2A2A2A] rounded-lg overflow-hidden">
          <div className="px-3 py-2 border-b border-[#2A2A2A] flex items-center justify-between">
            <div className="flex items-center gap-2">
              <MessageSquare size={16} className="text-[#1E90FF]" />
              <h3 className="text-sm font-semibold text-[#F5F5F5]">Live Chat & Events</h3>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-[#666666]">{sessionStats.calls} calls · ${sessionStats.cost_usd.toFixed(4)}</span>
              {(eventLog.length > 0 || chatHistory.length > 0) && (
                <button onClick={() => { setEventLog([]); setChatHistory([]); }} className="text-[#666666] hover:text-[#EF4444] transition-colors" title="Clear all">
                  <Trash2 size={12} />
                </button>
              )}
            </div>
          </div>

          <div ref={chatScrollRef} className="flex-1 overflow-y-auto p-3 space-y-3">
            {eventLog.length === 0 && chatHistory.length === 0 && (
              <div className="text-center text-xs text-[#666666] py-8 space-y-2">
                <p>Capture a frame to see AI analysis here.</p>
                <p>Use &quot;Capture + Audio&quot; to analyze both simultaneously.</p>
              </div>
            )}

            {eventLog.length > 0 && (
              <div className="space-y-2">
                <div className="text-[10px] text-[#666666] uppercase tracking-wide">Recent Captures (oldest first)</div>
                {eventLog.map((entry, idx) => (
                  <EventLogItem key={`${entry.captured_at}-${idx}`} entry={entry} severityColor={severityColor} />
                ))}
              </div>
            )}

            {chatHistory.length > 0 && (
              <div className="space-y-2 pt-2 border-t border-[#2A2A2A]">
                <div className="text-[10px] text-[#666666] uppercase tracking-wide">Conversation</div>
                {chatHistory.map((msg, idx) => (
                  <div key={idx} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                    <div className={`max-w-[85%] rounded-lg p-2 text-xs ${msg.role === "user" ? "bg-[#1E90FF] text-white" : "bg-[#1A1A1A] text-[#F5F5F5] border border-[#2A2A2A]"}`}>
                      <p className="whitespace-pre-wrap wrap-break-word">{msg.content}</p>
                      {msg.meta && <p className="mt-1 text-[9px] opacity-60">{msg.meta.total_tokens} tok · {msg.meta.latency_ms}ms</p>}
                    </div>
                  </div>
                ))}
                {chatLoading && (
                  <div className="flex justify-start">
                    <div className="bg-[#1A1A1A] border border-[#2A2A2A] rounded-lg p-2 text-xs text-[#A3A3A3] flex items-center gap-2">
                      <Loader2 size={12} className="animate-spin" /> Thinking...
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="border-t border-[#2A2A2A] p-2 space-y-2">
            <div className="flex flex-wrap gap-1">
              {["What's happening now?", "Any safety concerns?", "Count people and objects", "Summarize the last 5 captures"].map((q) => (
                <button key={q} onClick={() => sendChat(q)} disabled={chatLoading}
                  className="text-[10px] px-2 py-1 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded hover:text-[#F5F5F5] hover:border-[#1E90FF] transition-colors disabled:opacity-50">
                  {q}
                </button>
              ))}
            </div>
            <form onSubmit={(e) => { e.preventDefault(); sendChat(chatInput); }} className="flex gap-2">
              <input
                type="text" value={chatInput} onChange={(e) => setChatInput(e.target.value)}
                placeholder="Ask about the scene..." disabled={chatLoading}
                className="flex-1 px-3 py-1.5 text-xs bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5] placeholder-[#666666] focus:outline-none focus:border-[#1E90FF] disabled:opacity-50"
              />
              <button type="button" onClick={() => sendChat(chatInput || "What do you see in the current frame?", true)}
                disabled={chatLoading || !lastFrameRef.current}
                className="px-2 py-1.5 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded hover:text-[#1E90FF] disabled:opacity-30 transition-colors" title="Send with current frame">
                <Camera size={14} />
              </button>
              <button type="submit" disabled={chatLoading || !chatInput.trim()}
                className="px-3 py-1.5 bg-[#1E90FF] text-white rounded hover:bg-[#3BA0FF] disabled:opacity-50 transition-colors">
                <Send size={14} />
              </button>
            </form>
          </div>
        </div>
      </div>

    </div>
  );
}

function formatDuration(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

const SOURCE_BADGE: Record<string, string> = {
  combined: "bg-[#1E90FF]/20 text-[#1E90FF] border-[#1E90FF]/30",
  visual:   "bg-[#4ADE80]/10 text-[#4ADE80] border-[#4ADE80]/20",
  audio:    "bg-[#FBBF24]/10 text-[#FBBF24] border-[#FBBF24]/20",
};

function EventLogItem({ entry, severityColor }: { entry: EventLogEntry; severityColor: (s: string) => string }) {
  const c = entry.combinedResult;
  const r = entry.result;
  const a = entry.audioResult;
  const time = new Date(entry.captured_at).toLocaleTimeString();
  const totalObjects = (r.objects?.boxes || 0) + (r.objects?.bags || 0) + (r.objects?.pallets || 0) + (r.objects?.packages || 0);

  return (
    <div className="bg-[#1A1A1A] border border-[#2A2A2A] rounded-lg p-2 space-y-1.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-[#666666] font-mono">{time}</span>
          {c && <span className="text-[10px] text-[#1E90FF] border border-[#1E90FF]/20 rounded px-1 flex items-center gap-0.5"><Camera size={9} /><Mic size={9} /> combined</span>}
          {a && !c && <span className="text-[10px] text-[#FBBF24] border border-[#FBBF24]/20 rounded px-1 flex items-center gap-0.5"><Mic size={9} /> audio</span>}
        </div>
        <div className="flex items-center gap-2 text-[10px]">
          {r.person_count > 0 && <span className="text-[#A3A3A3]">👤 {r.person_count}</span>}
          {(r.vehicles?.length || 0) > 0 && <span className="text-[#A3A3A3]">🚘 {r.vehicles?.length}</span>}
          {totalObjects > 0 && <span className="text-[#A3A3A3]">📦 {totalObjects}</span>}
        </div>
      </div>

      <p className="text-xs text-[#A3A3A3] leading-tight">{c ? c.scene_summary : r.scene_summary}</p>

      {/* Combined unified events */}
      {c && c.events.length > 0 && (
        <div className="space-y-1 pt-1 border-t border-[#2A2A2A]">
          {c.events.map((e, idx) => (
            <div key={idx} className="text-xs flex items-start gap-1.5">
              <span className={`shrink-0 text-[9px] border rounded px-1 py-0.5 font-medium uppercase ${SOURCE_BADGE[e.source] ?? SOURCE_BADGE.visual}`}>
                {e.source === "combined" ? "A+V" : e.source === "audio" ? "🎙" : "👁"}
              </span>
              <span>
                <span className={`uppercase font-medium ${severityColor(e.severity)}`}>[{e.severity}]</span>{" "}
                <span className="text-[#F5F5F5]">{e.event_type.replace(/_/g, " ")}</span>{" "}
                <span className="text-[#666666]">— {e.description}</span>
              </span>
            </div>
          ))}
          {c.audio && (
            <div className="text-[9px] text-[#666666] flex items-center gap-1 pt-0.5">
              <Volume2 size={9} /> {c.audio.ambient_level} · {c.audio.dominant_sound}
              {c.audio.speech_detected && c.audio.speech_summary && <> · &quot;{c.audio.speech_summary}&quot;</>}
            </div>
          )}
        </div>
      )}

      {c && c.events.length === 0 && (
        <div className="pt-1 border-t border-[#2A2A2A]">
          <p className="text-[10px] text-[#666666] italic">No events · <Volume2 size={9} className="inline" /> {c.audio?.ambient_level} · {c.audio?.dominant_sound}</p>
        </div>
      )}

      {/* Frame-only events (no combined) */}
      {!c && r.events.length > 0 && (
        <div className="space-y-1 pt-1 border-t border-[#2A2A2A]">
          <div className="text-[9px] text-[#666666] uppercase flex items-center gap-1"><Camera size={9} /> Visual</div>
          {r.events.map((e, idx) => (
            <div key={idx} className="text-xs">
              <span className={`uppercase font-medium ${severityColor(e.severity)}`}>[{e.severity}]</span>{" "}
              <span className="text-[#F5F5F5]">{e.event_type.replace(/_/g, " ")}</span>{" "}
              <span className="text-[#666666]">— {e.description}</span>
            </div>
          ))}
        </div>
      )}

      {/* Standalone audio events */}
      {!c && a && (
        <div className="pt-1 border-t border-[#2A2A2A] space-y-1">
          <div className="text-[9px] text-[#666666] uppercase flex items-center gap-1"><Volume2 size={9} /> Audio · {a.ambient_level} · {a.dominant_sound}</div>
          {a.events.map((e, idx) => (
            <div key={idx} className="text-xs">
              <span className={`uppercase font-medium ${severityColor(e.severity)}`}>[{e.severity}]</span>{" "}
              <span className="text-[#F5F5F5]">{e.event_type.replace(/_/g, " ")}</span>{" "}
              <span className="text-[#666666]">— {e.description}</span>
            </div>
          ))}
        </div>
      )}

      {!c && r.events.length === 0 && !a && <p className="text-[10px] text-[#666666] italic">No events</p>}
    </div>
  );
}

function StatBox({ label, value, color = "#F5F5F5" }: { label: string; value: number | string; color?: string }) {
  return (
    <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-2 text-center">
      <div className="text-xs text-[#666666] uppercase">{label}</div>
      <div className="text-lg font-bold" style={{ color }}>{value}</div>
    </div>
  );
}

function YoloGateBadge({ decision, yolo }: { decision: "drop" | "escalate" | "fastpath"; yolo: YoloGateInfo }) {
  const config: Record<string, { label: string; color: string; note: string }> = {
    drop: { label: "DROPPED", color: "#666666", note: "No relevant objects detected locally — Gemini was not called." },
    fastpath: { label: "FAST-PATHED", color: "#4ADE80", note: "High-confidence local detection — Gemini was not called." },
    escalate: { label: "ESCALATED", color: "#1E90FF", note: "Escalated to Gemini for a full analysis." },
  };
  const c = config[decision] ?? config.escalate;
  return (
    <div className="bg-[#111111] border rounded-lg p-2 text-xs flex items-center justify-between gap-2 flex-wrap" style={{ borderColor: c.color }}>
      <div className="flex items-center gap-2">
        <span className="px-2 py-0.5 rounded font-bold" style={{ backgroundColor: `${c.color}20`, color: c.color }}>
          YOLO gate: {c.label}
        </span>
        <span className="text-[#A3A3A3]">{c.note}</span>
      </div>
      <span className="text-[#666666]">
        {yolo.detections.length} raw detection{yolo.detections.length === 1 ? "" : "s"} · {yolo.latency_ms}ms
      </span>
    </div>
  );
}

function SceneContextModal({ context, onSave, onClose }: {
  context: SceneContext;
  onSave: (ctx: SceneContext, enabled: boolean) => void;
  onClose: () => void;
}) {
  const [local, setLocal] = useState(context);

  const fieldRow = (key: keyof SceneContext, label: string, placeholder: string) => (
    <div>
      <label className="text-xs text-[#A3A3A3] mb-1 block">{label}</label>
      <input type="text" value={local[key]} onChange={(e) => setLocal({ ...local, [key]: e.target.value })}
        placeholder={placeholder}
        className="w-full px-3 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5] placeholder-[#666666] focus:outline-none focus:border-[#1E90FF]"
      />
    </div>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-2xl bg-[#111111] border border-[#2A2A2A] rounded-lg p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-[#F5F5F5]">Scene Context</h2>
            <p className="text-xs text-[#666666] mt-1">Tell the AI what&apos;s in the scene to reduce false positives.</p>
          </div>
          <button onClick={onClose} className="text-[#666666] hover:text-[#F5F5F5]"><X size={20} /></button>
        </div>
        <div className="space-y-3 mb-4">
          {fieldRow("center", "Center", "e.g., loading dock with conveyor belt")}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {fieldRow("left", "Left side", "e.g., storage racks with boxes")}
            {fieldRow("right", "Right side", "e.g., parking area for forklifts")}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {fieldRow("top", "Top / Far", "e.g., warehouse ceiling with lights")}
            {fieldRow("bottom", "Bottom / Near", "e.g., concrete floor with floor markings")}
          </div>
          {fieldRow("background", "Background / Other", "e.g., main entrance door, fire extinguisher on wall")}
        </div>
        <div className="flex items-center justify-between gap-2">
          <button onClick={() => setLocal(EMPTY_CONTEXT)} className="text-xs text-[#666666] hover:text-[#EF4444]">Clear all</button>
          <div className="flex gap-2">
            <button onClick={() => onSave(local, false)} className="px-4 py-2 text-sm text-[#A3A3A3] hover:text-[#F5F5F5] transition-colors">Save & Disable</button>
            <button onClick={() => onSave(local, true)} className="px-4 py-2 bg-[#1E90FF] text-white text-sm rounded-md hover:bg-[#3BA0FF] transition-colors">Save & Use Context</button>
          </div>
        </div>
      </div>
    </div>
  );
}
