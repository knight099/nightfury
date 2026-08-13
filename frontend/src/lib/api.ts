import type {
  AgentSummary,
  AlertRule,
  Camera,
  ChatMessage,
  CompileSequenceMessage,
  CompileSequenceResponse,
  ConversationSummary,
  Digest,
  DigestListResponse,
  DigestPreferences,
  DigestRequest,
  DiscoverResponse,
  Event,
  EventStats,
  PaginatedResponse,
  PairCodeResponse,
  Site,
  User,
  WhatsAppAlertContact,
} from "@/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "https://nightfury-backend.vercel.app";

type CreateCameraRequest = {
  name: string;
  site_id: string;
  ingest_mode: "rtsp_pull" | "rtmp_push" | "srt_push";
  rtsp_url?: string;
  stream_key?: string;
  enabled_events?: string[];
  detection_zones?: Array<Record<string, unknown>>;
  sensitivity?: "low" | "medium" | "high";
  idle_fps?: number;
  active_fps?: number;
};

class ApiClient {
  private token: string | null = null;

  setToken(token: string) {
    this.token = token;
  }

  clearToken() {
    this.token = null;
  }

  async request<T>(path: string, options?: RequestInit): Promise<T> {
    const res = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(this.token && { Authorization: `Bearer ${this.token}` }),
        ...options?.headers,
      },
    });

    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Request failed" }));
      throw new Error(error.detail || `HTTP ${res.status}`);
    }

    if (res.status === 204) return undefined as T;
    return res.json();
  }

  // Auth
  async login(username: string, password: string) {
    return this.request<{ token: string; user: User }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
  }

  async signup(username: string, password: string, name: string, org_name: string) {
    return this.request<{ token: string; user: User }>("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify({ username, password, name, org_name }),
    });
  }

  async logout() {
    return this.request<{ status: string }>("/api/auth/logout", { method: "POST" });
  }

  async changePassword(newPassword: string) {
    return this.request<{ status: string }>("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ new_password: newPassword }),
    });
  }

  async getMe() {
    return this.request<User>("/api/auth/me");
  }

  // Cameras
  async getCameras(params?: { site_id?: string; include_deleted?: boolean }) {
    const qs = new URLSearchParams(
      Object.entries(params || {}).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)])
    ).toString();
    return this.request<Camera[]>(`/api/cameras${qs ? `?${qs}` : ""}`);
  }

  async createCamera(data: CreateCameraRequest) {
    return this.request<{ camera: Camera; ingest_endpoint?: string; stream_key?: string }>("/api/cameras", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async updateCamera(id: string, data: Partial<Camera>) {
    return this.request<Camera>(`/api/cameras/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  async deleteCamera(id: string) {
    return this.request<void>(`/api/cameras/${id}`, { method: "DELETE" });
  }

  async compileSequence(cameraId: string, conversationId: string | null, message: string) {
    return this.request<CompileSequenceResponse>(`/api/cameras/${cameraId}/compile-sequence`, {
      method: "POST",
      body: JSON.stringify({ conversation_id: conversationId, message }),
    });
  }

  async getCompileSequenceConversation(cameraId: string, conversationId: string) {
    return this.request<{ messages: CompileSequenceMessage[] }>(
      `/api/cameras/${cameraId}/compile-sequence/${conversationId}`
    );
  }

  async restoreCamera(id: string) {
    return this.request<Camera>(`/api/cameras/${id}/restore`, { method: "POST" });
  }

  async getCameraLatestFrame(cameraId: string): Promise<{ url: string; updated_at: string } | null> {
    const res = await fetch(`${BASE_URL}/api/cameras/${cameraId}/latest-frame`, {
      headers: {
        ...(this.token && { Authorization: `Bearer ${this.token}` }),
      },
    });
    if (res.status === 404) return null;
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Request failed" }));
      throw new Error(error.detail || `HTTP ${res.status}`);
    }
    return res.json();
  }

  async getCameraStreamUrl(cameraId: string): Promise<{ url: string; expires_at: number }> {
    return this.request(`/api/cameras/${cameraId}/stream-url`);
  }

  async cameraWebRTCOffer(cameraId: string, offer: string): Promise<{ answer: string }> {
    return this.request<{ answer: string }>(`/api/cameras/${cameraId}/webrtc-offer`, {
      method: "POST",
      body: JSON.stringify({ offer }),
    });
  }

  async getIceServers(): Promise<{ iceServers: RTCIceServer[] }> {
    return this.request<{ iceServers: RTCIceServer[] }>("/api/webrtc/ice-servers");
  }

  // Events
  async getEvents(params: Record<string, string | number | undefined> = {}) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined) as [string, string][]
    ).toString();
    return this.request<PaginatedResponse<Event>>(`/api/events?${qs}`);
  }

  async getEvent(id: string) {
    return this.request<Event>(`/api/events/${id}`);
  }

  async submitFeedback(id: string, feedback: string, label?: string) {
    return this.request<{ status: string }>(`/api/events/${id}/feedback`, {
      method: "POST",
      body: JSON.stringify({ feedback, label }),
    });
  }

  async getEventStats(period: string = "24h") {
    return this.request<EventStats>(`/api/events/stats?period=${period}`);
  }

  // Sites
  async getSites(params?: { include_deleted?: boolean }) {
    const qs = params?.include_deleted ? "?include_deleted=true" : "";
    return this.request<Site[]>(`/api/sites${qs}`);
  }

  async createSite(data: { name: string; address?: string; timezone?: string }) {
    return this.request<Site>("/api/sites", { method: "POST", body: JSON.stringify(data) });
  }

  async updateSite(id: string, data: { name?: string; address?: string; timezone?: string }) {
    return this.request<Site>(`/api/sites/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  async deleteSite(id: string) {
    return this.request<void>(`/api/sites/${id}`, { method: "DELETE" });
  }

  async restoreSite(id: string) {
    return this.request<Site>(`/api/sites/${id}/restore`, { method: "POST" });
  }

  // Alert Rules
  async getAlertRules(params?: { include_deleted?: boolean }) {
    const qs = params?.include_deleted ? "?include_deleted=true" : "";
    return this.request<AlertRule[]>(`/api/alerts/rules${qs}`);
  }

  async createAlertRule(data: Partial<AlertRule>) {
    return this.request<AlertRule>("/api/alerts/rules", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async updateAlertRule(id: string, data: Partial<AlertRule>) {
    return this.request<AlertRule>(`/api/alerts/rules/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  async deleteAlertRule(id: string) {
    return this.request<void>(`/api/alerts/rules/${id}`, { method: "DELETE" });
  }

  async restoreAlertRule(id: string) {
    return this.request<AlertRule>(`/api/alerts/rules/${id}/restore`, { method: "POST" });
  }

  // Settings (org owner)
  async getMyOrg() {
    return this.request<{ id: string; name: string; slug: string; plan: string; settings: Record<string, unknown>; created_at: string }>("/api/settings/org");
  }

  async updateMyOrg(data: { name?: string; plan?: string }) {
    return this.request<{ id: string; name: string; slug: string; plan: string; created_at: string }>("/api/settings/org", {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  async getTeam() {
    return this.request<User[]>("/api/settings/team");
  }

  async updateTeamMember(userId: string, data: { name?: string; role?: string; is_active?: boolean }) {
    return this.request<User>(`/api/settings/team/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  async removeTeamMember(userId: string) {
    return this.request<void>(`/api/settings/team/${userId}`, { method: "DELETE" });
  }

  async resetTeamMemberPassword(userId: string, newPassword: string) {
    return this.request<{ status: string }>(`/api/settings/team/${userId}/reset-password`, {
      method: "POST",
      body: JSON.stringify({ new_password: newPassword }),
    });
  }

  async getWhatsAppAlertContacts() {
    return this.request<WhatsAppAlertContact[]>("/api/settings/whatsapp-alerts");
  }

  async addWhatsAppAlertContact(number: string) {
    return this.request<WhatsAppAlertContact[]>("/api/settings/whatsapp-alerts", {
      method: "POST",
      body: JSON.stringify({ number }),
    });
  }

  async updateWhatsAppAlertContact(id: string, data: { number?: string; enabled?: boolean }) {
    return this.request<WhatsAppAlertContact[]>(`/api/settings/whatsapp-alerts/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  async deleteWhatsAppAlertContact(id: string) {
    return this.request<WhatsAppAlertContact[]>(`/api/settings/whatsapp-alerts/${id}`, { method: "DELETE" });
  }

  // Admin
  async adminGetAiUsage(orgId: string, days = 30, limit = 100) {
    return this.request<{
      period_days: number;
      aggregate: { calls: number; prompt_tokens: number; output_tokens: number; total_tokens: number; cost_usd: number; avg_latency_ms: number };
      recent: { id: string; timestamp: string; username: string; model: string; operation: string; total_tokens: number; cost_usd: number }[];
    }>(`/api/admin/ai-usage?org_id=${orgId}&days=${days}&limit=${limit}`);
  }

  async adminGetOrgs(includeDeleted = false) {
    const qs = includeDeleted ? "?include_deleted=true" : "";
    return this.request<{ id: string; name: string; slug: string; plan: string; created_at: string; deleted_at: string | null }[]>(`/api/admin/orgs${qs}`);
  }

  async adminGetOrgsHealth() {
    return this.request<
      {
        org_id: string;
        name: string;
        plan: string;
        camera_count: number;
        cameras_online: number;
        cameras_offline: number;
        events_last_24h: number;
        events_last_7d: number;
        last_event_at: string | null;
      }[]
    >("/api/admin/orgs-health");
  }

  async adminGetUsers(params?: { org_id?: string; role?: string; include_deleted?: boolean }) {
    const qs = new URLSearchParams(
      Object.entries(params || {}).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)])
    ).toString();
    return this.request<User[]>(`/api/admin/users${qs ? `?${qs}` : ""}`);
  }

  async adminCreateUser(data: { username: string; password: string; name: string; org_id: string; role: string; must_change_password?: boolean }) {
    return this.request<User>("/api/admin/users/create", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async adminUpdateUser(userId: string, data: { username?: string; name?: string; role?: string; is_active?: boolean; org_id?: string }) {
    return this.request<User>(`/api/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  async adminChangePassword(userId: string, newPassword: string) {
    return this.request<{ status: string }>(`/api/admin/users/${userId}/change-password`, {
      method: "POST",
      body: JSON.stringify({ new_password: newPassword }),
    });
  }

  async adminForceLogout(userId: string) {
    return this.request<{ status: string }>(`/api/admin/users/${userId}/force-logout`, {
      method: "POST",
    });
  }

  async adminGetUserSessions(userId: string) {
    return this.request<{ sessions: Record<string, unknown>[] }>(
      `/api/admin/users/${userId}/sessions`
    );
  }

  async adminDeleteUser(userId: string) {
    return this.request<void>(`/api/admin/users/${userId}`, { method: "DELETE" });
  }

  async adminRestoreUser(userId: string) {
    return this.request<User>(`/api/admin/users/${userId}/restore`, { method: "POST" });
  }

  async adminCreateOrg(data: { name: string; plan?: string }) {
    return this.request<{ id: string; name: string; slug: string; plan: string; created_at: string }>("/api/admin/orgs", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async adminUpdateOrg(orgId: string, data: { name?: string; plan?: string }) {
    return this.request<{ id: string; name: string; slug: string; plan: string; created_at: string }>(`/api/admin/orgs/${orgId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  async adminDeleteOrg(orgId: string) {
    return this.request<void>(`/api/admin/orgs/${orgId}`, { method: "DELETE" });
  }

  async adminRestoreOrg(orgId: string) {
    return this.request<{ id: string; name: string; slug: string; plan: string; created_at: string; deleted_at: string | null }>(`/api/admin/orgs/${orgId}/restore`, { method: "POST" });
  }

  // Digests
  async getDigests(limit = 20, offset = 0) {
    return this.request<DigestListResponse>(`/api/digests?limit=${limit}&offset=${offset}`);
  }

  async getDigest(id: string) {
    return this.request<Digest>(`/api/digests/${id}`);
  }

  async createDigest(body: DigestRequest) {
    return this.request<Digest>("/api/digests", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  async getDigestPreferences() {
    return this.request<DigestPreferences>("/api/digests/preferences");
  }

  async updateDigestPreferences(body: Partial<DigestPreferences>) {
    return this.request<DigestPreferences>("/api/digests/preferences", {
      method: "PUT",
      body: JSON.stringify(body),
    });
  }

  // Chat
  async chatSend(body: {
    message: string;
    conversation_id?: string;
    camera_id?: string | null;
    event_id?: string | null;
    org_id?: string;
  }) {
    return this.request<ChatMessage>("/api/chat", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  async chatListConversations() {
    return this.request<ConversationSummary[]>("/api/chat/conversations");
  }

  async chatGetMessages(conversationId: string) {
    return this.request<ChatMessage[]>(`/api/chat/conversations/${conversationId}/messages`);
  }

  async chatDeleteConversation(conversationId: string) {
    return this.request<void>(`/api/chat/conversations/${conversationId}`, {
      method: "DELETE",
    });
  }

  // Agents (home NVR pairing)
  async createPairCode(): Promise<PairCodeResponse> {
    return this.request<PairCodeResponse>("/api/agents/pair-codes", {
      method: "POST",
    });
  }

  async listAgents(): Promise<{ agents: AgentSummary[] }> {
    return this.request<{ agents: AgentSummary[] }>("/api/agents");
  }

  async registerAgentCamera(
    agentId: string,
    body: { name: string; site_id?: string; rtsp_url: string }
  ): Promise<{ camera_id: string; status: string }> {
    return this.request<{ camera_id: string; status: string }>(`/api/agents/${agentId}/cameras`, {
      method: "POST",
      body: JSON.stringify({ ...body, site_id: body.site_id || undefined }),
    });
  }

  async discoverAgentCameras(agentId: string): Promise<DiscoverResponse> {
    return this.request<DiscoverResponse>(`/api/agents/${agentId}/discover`, {
      method: "POST",
      body: JSON.stringify({}),
    });
  }

  async registerAgentCameraFromOnvif(
    agentId: string,
    body: { name: string; site_id?: string; onvif_xaddr: string; user?: string; pass?: string }
  ): Promise<{ camera_id: string; status: string }> {
    return this.request<{ camera_id: string; status: string }>(`/api/agents/${agentId}/cameras`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  // Device-initiated provisioning
  async claimDevice(code: string, orgId?: string): Promise<{ agent_id: string; org_id: string; message: string }> {
    return this.request<{ agent_id: string; org_id: string; message: string }>("/api/devices/claim", {
      method: "POST",
      body: JSON.stringify({ code, ...(orgId ? { org_id: orgId } : {}) }),
    });
  }
}

export const api = new ApiClient();
