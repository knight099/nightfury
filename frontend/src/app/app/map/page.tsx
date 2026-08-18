"use client";

import { CameraMap } from "@/components/map/CameraMap";

// The v2 shell renders the same component as the live UI, so the two shells
// cannot drift apart on a feature whose copy carries a privacy claim.
export default function MapPageV2() {
  return <CameraMap />;
}
