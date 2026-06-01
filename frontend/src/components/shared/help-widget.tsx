"use client";

import { useState, useRef, useEffect } from "react";
import { MessageCircleQuestion, X, Send, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

const QUICK_ACTIONS = [
  { label: "Camera not connecting", id: "camera-connect" },
  { label: "No events detected", id: "no-events" },
  { label: "Not receiving alerts", id: "no-alerts" },
  { label: "Stream keeps dropping", id: "stream-drop" },
  { label: "High false positives", id: "false-positives" },
  { label: "How to get RTSP URL", id: "rtsp-url" },
];

const KNOWLEDGE_BASE: Record<string, string> = {
  "camera-connect": `**Camera not connecting? Try these steps:**

1. **Check the RTSP URL format:**
   \`rtsp://username:password@IP:554/stream1\`
   Common ports: 554 (default), 8554, 10554

2. **For RTSP Pull mode:**
   • Ensure your camera has a public IP or port forwarding is set up
   • Test the URL with VLC Player first (Media → Open Network Stream)
   • Check firewall allows outbound from our servers

3. **For RTMP Push mode (recommended):**
   • Copy the ingest endpoint + stream key from the camera page
   • In your NVR: Settings → Network → RTMP → Add destination
   • Use H.264 encoding, 720p resolution recommended
   • Status should change to "online" within 30 seconds

4. **Common issues:**
   • Wrong credentials in RTSP URL
   • Camera on private network without port forwarding
   • NVR firmware doesn't support RTMP push (try updating)
   • ISP blocking RTSP port (use RTMP push instead)

Still stuck? Check your camera brand's manual for the exact RTSP path format.`,

  "no-events": `**No events being detected? Check these:**

1. **Camera status:** Go to Cameras page — is it showing "online"?
   • If offline → the stream isn't reaching us (see "Camera not connecting")

2. **Enabled events:** Make sure you've checked the event types you want
   • Edit camera → verify checkboxes are ticked

3. **Sensitivity too low:** Try switching from Low to Medium
   • Low = only very confident detections (may miss things)
   • Medium = balanced (recommended)
   • High = catches more but may have false positives

4. **No motion in scene:** We only analyze frames when motion is detected
   • If camera points at a static scene with no activity, that's expected
   • Point at an area with foot traffic to test

5. **Test it:** Walk in front of the camera — you should see a "person" event within 10-30 seconds

6. **Check the dashboard:** Events may be coming in but your filters might be hiding them
   • Remove all filters on the Events page
   • Check "All types" and "All severity"`,

  "no-alerts": `**Not receiving alert notifications?**

1. **Check alert rules exist:** Go to Alerts → make sure you have at least one enabled rule

2. **Rule configuration:**
   • Is the rule enabled? (green toggle)
   • Does severity match? If rule is "High+" but events are "Low", they won't trigger
   • Camera filter correct? Empty = all cameras
   • Time window? Check if current time falls within the rule's window

3. **Contact details:**
   • WhatsApp: Must include country code (+91...)
   • Email: Check spam folder
   • Webhook: Verify your endpoint returns 2xx

4. **Cooldown:** Default is 60 seconds
   • Same event type on same camera won't re-alert within cooldown
   • Try reducing cooldown to 10s for testing

5. **WhatsApp setup:**
   • WhatsApp Business API requires template approval
   • During testing, messages go to sandbox numbers only
   • Ask your admin if WhatsApp is fully configured

6. **Quick test:** Create a rule with min severity "Low" and cooldown 10s, then walk in front of a camera.`,

  "stream-drop": `**Stream keeps disconnecting?**

1. **Bandwidth check:**
   • Each 720p camera stream needs ~1-3 Mbps upload
   • 10 cameras ≈ 10-30 Mbps upload required
   • Run a speed test on the network where cameras are

2. **Connection stability:**
   • Use wired ethernet for NVR/cameras, not WiFi
   • Check for packet loss: \`ping -c 100 your-camera-ip\`
   • Any loss > 1% will cause stream issues

3. **RTSP specific:**
   • Switch to TCP transport (more reliable than UDP)
   • Reduce resolution to 720p if using 1080p/4K
   • Lower frame rate to 15fps or 10fps in camera settings

4. **RTMP specific:**
   • Check NVR isn't hitting upload bandwidth cap
   • Some NVRs have a limit on simultaneous RTMP streams
   • Try SRT protocol instead (better for unstable networks)

5. **Our side:**
   • We auto-reconnect up to 5 times with backoff
   • If stream drops >5 times in a row, camera goes to "error" status
   • Check Dashboard → camera card for error details

6. **Network tips:**
   • QoS: Prioritize RTMP/RTSP traffic on your router
   • Dedicated upload bandwidth for cameras if possible`,

  "false-positives": `**Too many false positive alerts?**

1. **Reduce sensitivity:**
   • Edit camera → change from High/Medium to Low
   • Low mode only fires on >85% confidence detections

2. **Use feedback:**
   • Go to Events → click ✗ (Reject) on false positives
   • This data trains the AI to be more accurate for YOUR cameras
   • Accuracy improves after ~50-100 feedback submissions

3. **Use detection zones:**
   • Edit camera → Draw Detection Zones
   • Only monitor specific areas (ignore trees, roads outside property)
   • This dramatically reduces false alerts from irrelevant motion

4. **Adjust alert rules:**
   • Set min severity to "High" instead of "Low"
   • Add time windows (e.g., only alert after 10pm)
   • Increase cooldown (60s → 300s) to reduce alert spam

5. **Common causes:**
   • Shadows/lighting changes triggering "person" detection
   • Animals being detected as people
   • Moving foliage/trees
   • Camera vibration in wind

6. **Long term:** The more feedback you give (approve ✓ correct, reject ✗ wrong), the better it gets. Expect <5% false positive rate after a month of feedback.`,

  "rtsp-url": `**How to find your camera's RTSP URL:**

**CP Plus:**
\`rtsp://admin:password@IP:554/cam/realmonitor?channel=1&subtype=0\`

**Hikvision:**
\`rtsp://admin:password@IP:554/Streaming/Channels/101\`
(101 = camera 1 main stream, 102 = camera 1 sub stream)

**Dahua:**
\`rtsp://admin:password@IP:554/cam/realmonitor?channel=1&subtype=0\`

**Axis:**
\`rtsp://user:pass@IP/axis-media/media.amp\`

**Generic ONVIF:**
\`rtsp://user:pass@IP:554/stream1\`

**How to find it:**
1. Open your NVR/camera's web interface (type camera IP in browser)
2. Go to: Settings → Network → RTSP or Stream settings
3. Look for "RTSP URL" or "Stream path"
4. Replace IP with your public IP (if using port forwarding)

**Test before adding:**
• Open VLC → Media → Open Network Stream → paste URL
• If it plays in VLC, it'll work with Nightwatch

**Port forwarding (for RTSP pull):**
1. Router admin → Port forwarding
2. External port 554 → Internal camera IP:554
3. Use your public IP in the RTSP URL

**Or use RTMP Push (easier, no port forwarding needed).**`,
};

export function HelpWidget() {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "Hi! I'm the Nightwatch help assistant. I can help you troubleshoot camera connections, missing events, alert issues, and more.\n\nChoose a topic below or type your question:",
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const addMessage = (role: "user" | "assistant", content: string) => {
    setMessages((prev) => [
      ...prev,
      { id: Date.now().toString(), role, content, timestamp: new Date() },
    ]);
  };

  const handleQuickAction = (actionId: string) => {
    const action = QUICK_ACTIONS.find((a) => a.id === actionId);
    if (!action) return;

    addMessage("user", action.label);
    setIsTyping(true);

    setTimeout(() => {
      const response = KNOWLEDGE_BASE[actionId] || "I don't have specific help for that yet. Try rephrasing or contact support.";
      addMessage("assistant", response);
      setIsTyping(false);
    }, 600);
  };

  const handleSend = () => {
    if (!input.trim()) return;

    const userMessage = input.trim().toLowerCase();
    addMessage("user", input.trim());
    setInput("");
    setIsTyping(true);

    setTimeout(() => {
      const response = matchQuery(userMessage);
      addMessage("assistant", response);
      setIsTyping(false);
    }, 800);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <>
      {/* Floating button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          "fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full flex items-center justify-center shadow-lg transition-all duration-300",
          isOpen
            ? "bg-[#2A2A2A] rotate-0"
            : "bg-[#1E90FF] hover:bg-[#3BA0FF] hover:scale-110"
        )}
      >
        {isOpen ? <X size={22} className="text-[#A3A3A3]" /> : <MessageCircleQuestion size={24} className="text-white" />}
      </button>

      {/* Chat panel */}
      {isOpen && (
        <div className="fixed bottom-24 right-6 z-50 w-96 h-[560px] bg-[#111111] border border-[#2A2A2A] rounded-xl shadow-2xl flex flex-col overflow-hidden animate-in slide-in-from-bottom-4 duration-300">
          {/* Header */}
          <div className="px-4 py-3 border-b border-[#2A2A2A] bg-[#0D0D0D]">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              <span className="text-sm font-medium">Nightwatch Help</span>
            </div>
            <p className="text-[10px] text-[#666666] mt-0.5">Connection troubleshooting & setup guide</p>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={cn(
                  "max-w-[85%]",
                  msg.role === "user" ? "ml-auto" : "mr-auto"
                )}
              >
                <div
                  className={cn(
                    "px-3 py-2 rounded-lg text-xs leading-relaxed",
                    msg.role === "user"
                      ? "bg-[#1E90FF] text-white rounded-br-sm"
                      : "bg-[#1A1A1A] text-[#D4D4D4] rounded-bl-sm border border-[#2A2A2A]"
                  )}
                >
                  <FormattedMessage content={msg.content} />
                </div>
              </div>
            ))}

            {isTyping && (
              <div className="flex gap-1 px-3 py-2 bg-[#1A1A1A] rounded-lg w-fit border border-[#2A2A2A]">
                <span className="w-1.5 h-1.5 rounded-full bg-[#666666] animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-[#666666] animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-[#666666] animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Quick actions (show only at start) */}
          {messages.length <= 2 && (
            <div className="px-4 pb-2">
              <div className="flex flex-wrap gap-1.5">
                {QUICK_ACTIONS.map((action) => (
                  <button
                    key={action.id}
                    onClick={() => handleQuickAction(action.id)}
                    className="px-2.5 py-1 text-[10px] bg-[#1A1A1A] border border-[#2A2A2A] rounded-full text-[#A3A3A3] hover:text-[#1E90FF] hover:border-[#1E90FF]/30 transition-colors"
                  >
                    {action.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Input */}
          <div className="px-3 py-3 border-t border-[#2A2A2A] bg-[#0D0D0D]">
            <div className="flex items-center gap-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Type your question..."
                className="flex-1 px-3 py-2 bg-[#1F1F1F] border border-[#2A2A2A] rounded-lg text-xs text-[#F5F5F5] placeholder-[#666666] focus:outline-none focus:border-[#1E90FF]"
              />
              <button
                onClick={handleSend}
                disabled={!input.trim()}
                className="p-2 rounded-lg bg-[#1E90FF] text-white disabled:opacity-30 disabled:cursor-not-allowed hover:bg-[#3BA0FF] transition-colors"
              >
                <Send size={14} />
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function FormattedMessage({ content }: { content: string }) {
  const parts = content.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return <strong key={i} className="text-[#F5F5F5] font-semibold">{part.slice(2, -2)}</strong>;
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return (
            <code key={i} className="px-1 py-0.5 bg-[#0D0D0D] text-[#1E90FF] rounded text-[10px] font-mono">
              {part.slice(1, -1)}
            </code>
          );
        }
        return <span key={i} style={{ whiteSpace: "pre-wrap" }}>{part}</span>;
      })}
    </>
  );
}

function matchQuery(query: string): string {
  const keywords: Record<string, string[]> = {
    "camera-connect": ["connect", "camera not", "cant connect", "can't connect", "connection", "offline", "add camera", "not working"],
    "no-events": ["no event", "not detecting", "no detection", "events not", "nothing detected", "not showing"],
    "no-alerts": ["no alert", "not receiving", "notification", "whatsapp not", "email not", "no notify"],
    "stream-drop": ["disconnect", "dropping", "keeps going offline", "unstable", "reconnect", "stream drop", "buffer"],
    "false-positives": ["false positive", "wrong alert", "incorrect", "too many", "false alarm", "not accurate"],
    "rtsp-url": ["rtsp", "url", "cp plus", "hikvision", "dahua", "axis", "stream url", "stream path"],
  };

  for (const [id, terms] of Object.entries(keywords)) {
    if (terms.some((term) => query.includes(term))) {
      return KNOWLEDGE_BASE[id];
    }
  }

  return `I'm not sure about that specific question, but here are some things I can help with:

• **Camera not connecting** — RTSP/RTMP setup, port forwarding
• **No events detected** — Sensitivity, enabled events, motion
• **Not receiving alerts** — Rule config, contacts, cooldown
• **Stream keeps dropping** — Bandwidth, stability, protocols
• **High false positives** — Sensitivity, zones, feedback
• **How to get RTSP URL** — Brand-specific URL formats

Click one of the quick actions above, or try rephrasing your question with keywords like "connect", "alert", "events", or your camera brand name.`;
}
