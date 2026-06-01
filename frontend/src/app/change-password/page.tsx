"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";

export default function ChangePasswordPage() {
  const router = useRouter();
  const { token, user, setAuth } = useAuthStore();
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!token || !user) {
      router.replace("/login");
    } else if (!user.must_change_password) {
      router.replace("/dashboard");
    }
  }, [token, user, router]);

  if (!token || !user || !user.must_change_password) {
    return null;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (newPassword.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    if (newPassword !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    setLoading(true);
    try {
      api.setToken(token);
      await api.changePassword(newPassword);
      setAuth(token, { ...user, must_change_password: false });
      router.push("/dashboard");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to change password");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0D0D0D]">
      <div className="w-full max-w-sm p-8 bg-[#111111] rounded-lg border border-[#2A2A2A]">
        <h1 className="text-2xl font-bold text-center mb-2">
          <span className="text-[#1E90FF]">N</span>IGHTWATCH
        </h1>
        <p className="text-sm text-[#FBBF24] text-center mb-2">
          Password Change Required
        </p>
        <p className="text-xs text-[#666666] text-center mb-6">
          Your account has a one-time password. Please set a new password to continue.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <input
            type="password"
            placeholder="New password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            className="w-full px-3 py-2 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5] placeholder-[#666666] focus:outline-none focus:border-[#1E90FF]"
            required
            minLength={8}
          />
          <input
            type="password"
            placeholder="Confirm new password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className="w-full px-3 py-2 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5] placeholder-[#666666] focus:outline-none focus:border-[#1E90FF]"
            required
            minLength={8}
          />

          {error && <p className="text-sm text-red-400">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 bg-[#1E90FF] text-white rounded-md text-sm font-medium hover:bg-[#3BA0FF] disabled:opacity-50 transition-colors"
          >
            {loading ? "..." : "Set New Password"}
          </button>
        </form>
      </div>
    </div>
  );
}
