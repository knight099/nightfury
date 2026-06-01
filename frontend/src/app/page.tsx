"use client";

import Link from "next/link";
import {
  Camera,
  Zap,
  Bell,
  Shield,
  Eye,
  BookOpen,
  ArrowRight,
  Wifi,
  Brain,
  Clock,
} from "lucide-react";

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-[#0D0D0D] text-[#F5F5F5]">
      {/* Nav */}
      <nav className="fixed top-0 inset-x-0 z-50 border-b border-[#2A2A2A] bg-[#0D0D0D]/80 backdrop-blur-md">
        <div className="mx-auto max-w-6xl px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Eye className="h-5 w-5 text-[#1E90FF]" />
            <span className="text-lg font-bold tracking-tight">Nightwatch</span>
          </div>
          <div className="flex items-center gap-4">
            <Link
              href="/login"
              className="text-sm text-[#A3A3A3] hover:text-[#F5F5F5] transition-colors"
            >
              Sign in
            </Link>
            <Link
              href="/login"
              className="text-sm bg-[#1E90FF] text-white px-4 py-2 rounded-lg hover:bg-[#3BA0FF] transition-colors"
            >
              Get started
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="pt-40 pb-28 px-6 text-center relative overflow-hidden">
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[400px] rounded-full bg-[#1E90FF]/6 blur-[120px]" />
        </div>

        <div className="relative mx-auto max-w-3xl">
          <div className="inline-flex items-center gap-2 text-xs text-[#1E90FF] bg-[#1E90FF]/10 border border-[#1E90FF]/20 rounded-full px-3 py-1 mb-6">
            <Zap className="h-3 w-3" />
            Powered by Gemini Vision AI
          </div>

          <h1 className="text-5xl md:text-6xl font-bold leading-tight tracking-tight mb-6">
            Your cameras.{" "}
            <span className="text-[#1E90FF]">Finally intelligent.</span>
          </h1>

          <p className="text-lg text-[#A3A3A3] max-w-xl mx-auto mb-10 leading-relaxed">
            Nightwatch turns any CCTV feed into a smart event stream — detecting
            threats, summarising nights, and alerting you on WhatsApp before you
            even check the footage.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link
              href="/login"
              className="w-full sm:w-auto flex items-center justify-center gap-2 bg-[#1E90FF] text-white px-6 py-3 rounded-lg text-sm font-medium hover:bg-[#3BA0FF] transition-colors"
            >
              Start monitoring <ArrowRight className="h-4 w-4" />
            </Link>
            <a
              href="#how-it-works"
              className="w-full sm:w-auto flex items-center justify-center gap-2 border border-[#2A2A2A] text-[#A3A3A3] px-6 py-3 rounded-lg text-sm hover:border-[#3BA0FF] hover:text-[#F5F5F5] transition-colors"
            >
              See how it works
            </a>
          </div>
        </div>
      </section>

      {/* Stats bar */}
      <section className="border-y border-[#2A2A2A] py-8 px-6">
        <div className="mx-auto max-w-4xl grid grid-cols-2 md:grid-cols-4 gap-8 text-center">
          {[
            { value: "~80%", label: "fewer API calls via motion gating" },
            { value: "<2s", label: "alert delivery on WhatsApp" },
            { value: "10s", label: "video clip per event" },
            { value: "2×/day", label: "AI digest — morning + evening" },
          ].map((s) => (
            <div key={s.label}>
              <div className="text-2xl font-bold text-[#1E90FF]">{s.value}</div>
              <div className="text-xs text-[#666666] mt-1">{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="py-24 px-6">
        <div className="mx-auto max-w-6xl">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-bold mb-3">
              Everything you need. Nothing you don&apos;t.
            </h2>
            <p className="text-[#666666] text-sm max-w-md mx-auto">
              Built for security teams and homeowners who want real intelligence,
              not endless footage to scrub through.
            </p>
          </div>

          <div className="grid md:grid-cols-3 gap-4">
            {[
              {
                icon: Brain,
                title: "Gemini Vision AI",
                desc: "Frames are analysed by Gemini 2.0 Flash only when motion is detected, keeping costs low without missing a thing.",
              },
              {
                icon: Bell,
                title: "Instant Alerts",
                desc: "WhatsApp, email, or webhook — the moment an event crosses your configured threshold, you know about it.",
              },
              {
                icon: BookOpen,
                title: "Morning & Evening Digests",
                desc: "A plain-language recap of what happened overnight or during the day, delivered on a schedule to your phone.",
              },
              {
                icon: Camera,
                title: "Any Camera, Any Brand",
                desc: "Works with CP Plus, Hikvision, Dahua, and any NVR that speaks RTSP or ONVIF — no port-forwarding required.",
              },
              {
                icon: Wifi,
                title: "No Port-Forwarding",
                desc: "Our LAN agent creates an outbound encrypted tunnel to the cloud. Your NVR stays on your local network.",
              },
              {
                icon: Shield,
                title: "Multi-Tenant & Isolated",
                desc: "Every org sees only its own data. Video never leaves the edge — only event snapshots and 10-second clips reach the cloud.",
              },
            ].map(({ icon: Icon, title, desc }) => (
              <div
                key={title}
                className="border border-[#2A2A2A] rounded-xl p-6 bg-[#111111] hover:border-[#1E90FF]/30 hover:bg-[#1A1A1A] transition-all"
              >
                <div className="h-9 w-9 rounded-lg bg-[#1E90FF]/10 flex items-center justify-center mb-4">
                  <Icon className="h-4 w-4 text-[#1E90FF]" />
                </div>
                <h3 className="font-semibold mb-2 text-sm text-[#F5F5F5]">{title}</h3>
                <p className="text-xs text-[#666666] leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how-it-works" className="py-24 px-6 border-t border-[#2A2A2A]">
        <div className="mx-auto max-w-4xl">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-bold mb-3">How it works</h2>
            <p className="text-[#666666] text-sm">From camera to alert in seconds.</p>
          </div>

          <div className="relative">
            <div className="absolute left-6 top-8 bottom-8 w-px bg-[#2A2A2A] hidden md:block" />

            <div className="space-y-8">
              {[
                {
                  step: "01",
                  icon: Camera,
                  title: "Connect your camera",
                  desc: "Install the Nightwatch LAN agent on any Pi, NAS, or router. It auto-discovers your NVR via ONVIF or you enter the RTSP URL manually. Pair with a 6-digit code — done in under 5 minutes.",
                },
                {
                  step: "02",
                  icon: Eye,
                  title: "AI watches so you don't have to",
                  desc: "Motion detection gates every frame. When something moves, Gemini Vision analyses the scene — classifying the event type, severity, and any relevant details. No motion, no API call.",
                },
                {
                  step: "03",
                  icon: Bell,
                  title: "Get notified instantly",
                  desc: "Alert rules you define trigger WhatsApp messages, emails, or webhooks the moment a match is found. A snapshot and 10-second clip are attached automatically.",
                },
                {
                  step: "04",
                  icon: Clock,
                  title: "Review your daily digest",
                  desc: "Every morning and evening, a plain-language summary of the previous period lands in your inbox — what happened, how many events, any patterns worth noting.",
                },
              ].map(({ step, icon: Icon, title, desc }) => (
                <div key={step} className="flex gap-6 relative">
                  <div className="flex-none h-12 w-12 rounded-full border border-[#2A2A2A] bg-[#0D0D0D] flex items-center justify-center z-10">
                    <Icon className="h-5 w-5 text-[#1E90FF]" />
                  </div>
                  <div className="pt-2 pb-8">
                    <div className="text-xs text-[#1E90FF] font-mono mb-1">{step}</div>
                    <h3 className="font-semibold mb-2 text-[#F5F5F5]">{title}</h3>
                    <p className="text-sm text-[#666666] leading-relaxed max-w-lg">{desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24 px-6">
        <div className="mx-auto max-w-2xl text-center border border-[#2A2A2A] rounded-2xl p-12 bg-[#111111]">
          <div className="h-12 w-12 rounded-xl bg-[#1E90FF]/10 flex items-center justify-center mx-auto mb-6">
            <Eye className="h-6 w-6 text-[#1E90FF]" />
          </div>
          <h2 className="text-3xl font-bold mb-4">
            Stop reviewing footage.
            <br />
            Start getting answers.
          </h2>
          <p className="text-[#666666] text-sm mb-8 max-w-sm mx-auto">
            Set up in minutes. Works with the cameras you already own.
          </p>
          <Link
            href="/login"
            className="inline-flex items-center gap-2 bg-[#1E90FF] text-white px-8 py-3 rounded-lg text-sm font-medium hover:bg-[#3BA0FF] transition-colors"
          >
            Get started free <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-[#2A2A2A] py-8 px-6">
        <div className="mx-auto max-w-6xl flex flex-col md:flex-row items-center justify-between gap-4 text-xs text-[#666666]">
          <div className="flex items-center gap-2">
            <Eye className="h-4 w-4 text-[#1E90FF]" />
            <span>Nightwatch</span>
          </div>
          <span>AI-powered CCTV event intelligence</span>
          <Link href="/login" className="hover:text-[#A3A3A3] transition-colors">
            Sign in →
          </Link>
        </div>
      </footer>
    </div>
  );
}
