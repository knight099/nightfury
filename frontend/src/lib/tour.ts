import { driver } from "driver.js";
import "driver.js/dist/driver.css";

export function startOnboardingTour(onComplete?: () => void) {
  const driverObj = driver({
    showProgress: true,
    animate: true,
    overlayColor: "rgba(0, 0, 0, 0.85)",
    stagePadding: 8,
    stageRadius: 8,
    popoverClass: "nightwatch-tour-popover",
    nextBtnText: "Next →",
    prevBtnText: "← Back",
    doneBtnText: "Get Started!",
    onDestroyed: () => {
      localStorage.setItem(getTourKey(), "true");
      onComplete?.();
    },
    steps: [
      {
        popover: {
          title: "👋 Welcome to Nightwatch",
          description:
            "Let's walk you through how to connect your cameras and start receiving AI-powered event alerts. This takes about 2 minutes.",
          side: "over" as const,
          align: "center" as const,
        },
      },
      {
        popover: {
          title: "Step 1: How It Works",
          description:
            "Nightwatch connects to your existing camera feeds, runs AI analysis on the video, and sends you instant alerts when events are detected. No camera replacement needed — works with any IP camera.",
          side: "over" as const,
          align: "center" as const,
        },
      },
      {
        element: "[data-tour='nav-cameras']",
        popover: {
          title: "Step 2: Add Your Cameras",
          description:
            "Go to Cameras to connect your first camera. You have two options:\n\n• **RTSP Pull** — Give us your camera's RTSP URL and we'll pull the stream\n• **RTMP Push** — We give you an endpoint, and your NVR pushes the stream to us",
          side: "right" as const,
          align: "start" as const,
        },
      },
      {
        popover: {
          title: "Step 2a: RTSP Pull Mode",
          description:
            "If your camera has a public IP or you've set up port forwarding:\n\n1. Find your camera's RTSP URL (usually in your NVR settings)\n2. Format: `rtsp://user:pass@IP:554/stream`\n3. Paste it when adding the camera\n\nWe'll connect and start analyzing frames immediately.",
          side: "over" as const,
          align: "center" as const,
        },
      },
      {
        popover: {
          title: "Step 2b: RTMP Push Mode (Recommended)",
          description:
            "If your camera is behind a firewall (most cases):\n\n1. Add camera in 'Push' mode — we'll give you a URL + stream key\n2. In your NVR/VMS, add a new RTMP destination with that URL\n3. Start streaming — events will appear within seconds\n\nThis works like streaming to YouTube, but to our AI platform.",
          side: "over" as const,
          align: "center" as const,
        },
      },
      {
        popover: {
          title: "Step 3: Choose What to Detect",
          description:
            "When adding a camera, select which events to monitor:\n\n• 👤 Person detected\n• 🚗 Vehicle detected\n• 🚨 Intrusion (zone entry)\n• ⏱️ Loitering (person stays too long)\n• 👥 Crowd spike\n• 🔥 Fire/smoke\n• 🦺 PPE violations\n\nYou can change these anytime.",
          side: "over" as const,
          align: "center" as const,
        },
      },
      {
        popover: {
          title: "Step 4: Set Sensitivity",
          description:
            "Choose how sensitive the AI should be:\n\n• **Low** — Only very confident detections (fewer alerts, rarely wrong)\n• **Medium** — Balanced (recommended to start)\n• **High** — Catches more events (more alerts, some false positives)\n\nStart with Medium, adjust based on your results.",
          side: "over" as const,
          align: "center" as const,
        },
      },
      {
        element: "[data-tour='nav-alerts']",
        popover: {
          title: "Step 5: Configure Alerts",
          description:
            "Set up notification rules to get alerted:\n\n• **WhatsApp** — Instant messages with snapshot\n• **Email** — Detailed alert with event details\n• **Webhook** — POST to your own system\n\nYou can filter by event type, severity, time window, and specific cameras.",
          side: "right" as const,
          align: "start" as const,
        },
      },
      {
        element: "[data-tour='nav-events']",
        popover: {
          title: "Step 6: Review Events",
          description:
            "Every detected event appears here with:\n\n• Annotated snapshot (bounding boxes)\n• 10-second video clip\n• AI description of what happened\n• Confidence score\n\n**Important:** Approve ✓ or Reject ✗ events — this trains the AI to be more accurate for YOUR specific cameras.",
          side: "right" as const,
          align: "start" as const,
        },
      },
      {
        element: "[data-tour='nav-dashboard']",
        popover: {
          title: "Step 7: Monitor Everything",
          description:
            "Your dashboard shows:\n\n• Real-time event feed\n• Camera health status\n• Event statistics\n• False positive rate (improves as you give feedback)\n\nKeep this open to monitor your site in real-time.",
          side: "right" as const,
          align: "start" as const,
        },
      },
      {
        popover: {
          title: "🎉 You're Ready!",
          description:
            "That's it! Here's the quick start:\n\n1. **Add a camera** (Cameras → Add Camera)\n2. **Set up an alert** (Alerts → New Rule)\n3. **Watch events roll in** (Dashboard)\n\nThe AI will start detecting events within seconds of your camera connecting. Approve/reject alerts to make it smarter over time.\n\nYou can replay this tour anytime from Settings.",
          side: "over" as const,
          align: "center" as const,
        },
      },
    ],
  });

  driverObj.drive();
}

function getTourKey(): string {
  try {
    const stored = localStorage.getItem("nightwatch-auth");
    if (stored) {
      const { state } = JSON.parse(stored);
      if (state?.user?.username) {
        return `nightwatch-tour-completed-${state.user.username}`;
      }
    }
  } catch {}
  return "nightwatch-tour-completed";
}

export function shouldShowTour(): boolean {
  return localStorage.getItem(getTourKey()) !== "true";
}

export function resetTour() {
  localStorage.removeItem(getTourKey());
}
