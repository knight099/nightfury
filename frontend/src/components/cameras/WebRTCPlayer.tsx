"use client";

import { useCallback, useEffect, useRef } from "react";
import { api } from "@/lib/api";

interface Props {
  cameraId: string;
  className?: string;
  /**
   * Called when live view cannot be established. `reason` carries the
   * server's message where one is available — the video wall needs to tell
   * "this appliance is at its viewer limit" apart from "this camera is
   * broken", because only one of those is the user's problem to fix.
   */
  onError: (reason?: string) => void;
}

export function WebRTCPlayer({ cameraId, className, onError }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);

  const handleError = useCallback(
    (reason?: string) => {
      onError(reason);
    },
    [onError]
  );

  useEffect(() => {
    let cancelled = false;

    async function connect() {
      try {
        let iceServers: RTCIceServer[] = [
          { urls: "stun:stun.l.google.com:19302" },
        ];
        try {
          const iceResult = await api.getIceServers();
          if (iceResult.iceServers?.length) {
            iceServers = iceResult.iceServers;
          }
        } catch {
          // TURN is a fallback path, not a hard requirement — if minting
          // credentials fails, proceed STUN-only rather than blocking live view.
        }
        if (cancelled) return;

        const pc = new RTCPeerConnection({ iceServers });
        pcRef.current = pc;

        pc.addTransceiver("video", { direction: "recvonly" });

        pc.ontrack = (event) => {
          if (videoRef.current && event.streams[0]) {
            videoRef.current.srcObject = event.streams[0];
          }
        };

        pc.onconnectionstatechange = () => {
          if (
            pc.connectionState === "failed" ||
            pc.connectionState === "disconnected" ||
            pc.connectionState === "closed"
          ) {
            if (!cancelled) handleError();
          }
        };

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        const result = await api.cameraWebRTCOffer(cameraId, offer.sdp!);
        if (cancelled) {
          pc.close();
          return;
        }

        await pc.setRemoteDescription({ type: "answer", sdp: result.answer });
      } catch (err) {
        if (!cancelled) {
          handleError(err instanceof Error ? err.message : undefined);
        }
      }
    }

    connect();

    return () => {
      cancelled = true;
      pcRef.current?.close();
      pcRef.current = null;
    };
  }, [cameraId, handleError]);

  return (
    <video
      ref={videoRef}
      autoPlay
      muted
      playsInline
      className={className}
    />
  );
}
