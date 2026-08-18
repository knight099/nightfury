import { AppShell } from "@/components/layout/app-shell";

export default function PageLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
