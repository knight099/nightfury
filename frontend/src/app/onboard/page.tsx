import { redirect } from "next/navigation";

/**
 * The old four-step installer is gone. It duplicated /app/cameras/connect
 * with an incompatible model (dashboard-generated code pasted into a local
 * agent UI, versus the device-initiated code the box now prints itself),
 * and its final step verified the wrong thing.
 *
 * Kept as a redirect rather than deleted: this URL is in pilot install
 * notes and support replies, and a 404 to a customer mid-install is worse
 * than an extra file.
 */
export default function OnboardRedirect() {
  redirect("/app/cameras/connect");
}
