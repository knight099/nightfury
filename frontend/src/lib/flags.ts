export function isNewUiEnabled(): boolean {
  return process.env.NEXT_PUBLIC_NEW_UI === "true";
}
