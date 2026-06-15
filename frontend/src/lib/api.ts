import type {
  AgentSummary,
  AlertRule,
  Camera,
  ChatMessage,
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
} from "@/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

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
  async getCameras(params?: { site_id?: string }) {
    const qs = params?.site_id ? `?site_id=${params.site_id}` : "";
    return this.request<Camera[]>(`/api/cameras${qs}`);
  }

  async createCamera(data: Partial<Camera> & { name: string; site_id: string; ingest_mode: string }) {
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

  // Events
  async getEvents(params: Record<string, string | number | undefined> = {}) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined) as [string, string][]
    ).toString();
    return this.request<PaginatedResponse<Event>>(`/api/events?${qs}`);
  }

  async getEvent(id: string) {
    return this.request<{ event: Event }>(`/api/events/${id}`);
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
  async getSites() {
    return this.request<Site[]>("/api/sites");
  }

  async createSite(data: { name: string; address?: string; timezone?: string }) {
    return this.request<Site>("/api/sites", { method: "POST", body: JSON.stringify(data) });
  }

  // Alert Rules
  async getAlertRules() {
    return this.request<AlertRule[]>("/api/alerts/rules");
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

  // Admin
  async adminGetOrgs() {
    return this.request<{ id: string; name: string; slug: string; plan: string; created_at: string }[]>("/api/admin/orgs");
  }

  async adminGetUsers(params?: { org_id?: string; role?: string }) {
    const qs = new URLSearchParams(
      Object.entries(params || {}).filter(([, v]) => v !== undefined) as [string, string][]
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
}

export const api = new ApiClient();
