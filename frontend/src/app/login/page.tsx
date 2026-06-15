"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";

export default function LoginPage() {
  const router = useRouter();
  const { setAuth } = useAuthStore();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [isSignup, setIsSignup] = useState(false);
  const [name, setName] = useState("");
  const [orgName, setOrgName] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      let result;
      if (isSignup) {
        result = await api.signup(username, password, name, orgName);
      } else {
        result = await api.login(username, password);
      }
      api.setToken(result.token);
      setAuth(result.token, result.user);
      if (result.user.must_change_password) {
        router.push("/change-password");
      } else {
        router.push("/dashboard");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-dvh flex items-center justify-center bg-[#0D0D0D] px-4 relative overflow-hidden">
      <div
        className="pointer-events-none absolute -top-40 left-1/2 -translate-x-1/2 w-[600px] h-[400px] rounded-full opacity-20 blur-3xl"
        style={{ background: "radial-gradient(circle, #1E90FF 0%, transparent 70%)" }}
      />
      <div className="w-full max-w-sm p-6 sm:p-8 bg-[#111111] rounded-xl border border-[#2A2A2A] shadow-2xl relative">
        <h1 className="text-3xl font-bold text-center mb-2 font-heading tracking-tight">
          <span className="text-[#1E90FF]">N</span>IGHTWATCH
        </h1>
        <p className="text-sm text-[#A3A3A3] text-center mb-8">
          Your cameras, watched by AI — day and night.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          {isSignup && (
            <>
              <input
                type="text"
                placeholder="Your name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-3.5 py-3 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5] placeholder-[#666666] focus:outline-none focus:border-[#1E90FF]"
                required
              />
              <input
                type="text"
                placeholder="Organization name"
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
                className="w-full px-3.5 py-3 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5] placeholder-[#666666] focus:outline-none focus:border-[#1E90FF]"
                required
              />
            </>
          )}
          <input
            type="text"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            className="w-full px-3.5 py-3 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5] placeholder-[#666666] focus:outline-none focus:border-[#1E90FF]"
            required
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full px-3.5 py-3 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5] placeholder-[#666666] focus:outline-none focus:border-[#1E90FF]"
            required
          />

          {error && <p className="text-sm text-red-400">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 bg-[#1E90FF] text-white rounded-md text-sm font-semibold hover:bg-[#3BA0FF] disabled:opacity-50 glow-accent-hover transition-colors"
          >
            {loading ? "Signing in…" : isSignup ? "Create Account" : "Sign In"}
          </button>
        </form>

        <button
          onClick={() => setIsSignup(!isSignup)}
          className="w-full mt-4 text-xs text-[#666666] hover:text-[#A3A3A3] transition-colors"
        >
          {isSignup ? "Already have an account? Sign in" : "Need an account? Sign up"}
        </button>
      </div>
    </div>
  );
}
