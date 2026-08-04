// Stand-in for the real ApiClient (frontend/src/lib/api.ts) — same method
// names and return shapes, but resolves with sample data instead of
// hitting a real backend. Only implements the methods the copied
// components actually call.
import type {
  AlertRule,
  Camera,
  ChatMessage,
  CompileSequenceResponse,
  DigestPreferences,
} from "../../types";
import {
  sampleAlertRuleDraft,
  sampleCameras,
  sampleChatMessages,
  sampleDigestPreferences,
  sampleEvents,
} from "./samples";

function delay<T>(value: T, ms = 150): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

class MockApiClient {
  setToken(_token: string) {}

  async logout() {
    return delay({ status: "ok" });
  }

  async getCameras(_params?: { site_id?: string; include_deleted?: boolean }) {
    return delay<Camera[]>(sampleCameras);
  }

  async updateCamera(id: string, data: Partial<Camera>) {
    const base = sampleCameras.find((c) => c.id === id) ?? sampleCameras[0];
    return delay<Camera>({ ...base, ...data });
  }

  async getCameraLatestFrame(_cameraId: string) {
    return delay<{ url: string; updated_at: string } | null>(null);
  }

  async getCameraStreamUrl(_cameraId: string) {
    return delay({ url: "", expires_at: Date.now() + 15 * 60 * 1000 });
  }

  async cameraWebRTCOffer(_cameraId: string, _offer: string) {
    return delay({ answer: "" });
  }

  async getEvents(_params: Record<string, string | number | undefined> = {}) {
    return delay({ events: sampleEvents, total: sampleEvents.length, page: 1, pages: 1 });
  }

  async compileSequence(_cameraId: string, conversationId: string | null, _message: string) {
    return delay<CompileSequenceResponse>({
      conversation_id: conversationId ?? "conv-preview",
      type: "draft",
      message: null,
      steps: [],
      alert_rule: sampleAlertRuleDraft,
      warnings: [],
    });
  }

  async createAlertRule(data: Partial<AlertRule>) {
    return delay<AlertRule>({
      id: "rule-preview",
      org_id: "org-1",
      name: data.name ?? "New rule",
      cameras: data.cameras ?? [],
      event_types: data.event_types ?? [],
      min_severity: data.min_severity ?? "medium",
      time_window: data.time_window ?? null,
      zones: data.zones ?? [],
      notify_channels: data.notify_channels ?? [],
      notify_contacts: data.notify_contacts ?? [],
      webhook_url: data.webhook_url ?? null,
      cooldown_seconds: data.cooldown_seconds ?? 300,
      enabled: data.enabled ?? true,
      created_at: new Date().toISOString(),
    });
  }

  async getDigestPreferences() {
    return delay<DigestPreferences>(sampleDigestPreferences);
  }

  async updateDigestPreferences(body: Partial<DigestPreferences>) {
    return delay<DigestPreferences>({ ...sampleDigestPreferences, ...body });
  }

  async chatSend(body: {
    message: string;
    conversation_id?: string;
    camera_id?: string | null;
    event_id?: string | null;
    org_id?: string;
  }) {
    return delay<ChatMessage>({
      id: "msg-preview",
      conversation_id: body.conversation_id ?? "conv-preview",
      role: "assistant",
      content: sampleChatMessages[sampleChatMessages.length - 1].content,
      created_at: new Date().toISOString(),
    });
  }
}

export const api = new MockApiClient();
