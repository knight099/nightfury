"use client";

import CameraMapV2 from "@/components/v2/CameraMapV2";

// V2-styled rendering of the same data/logic as the V1 page
// (components/map/CameraMap.tsx). The privacy-caveat copy is imported from
// there rather than retyped, so the two shells can't drift on that claim.
export default function MapPageV2() {
  return <CameraMapV2 />;
}
