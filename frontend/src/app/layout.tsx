import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Nightwatch — AI CCTV Intelligence",
  description: "Event-based AI CCTV intelligence platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark h-full antialiased">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Comic+Relief&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-full bg-[#0D0D0D] text-[#F5F5F5]" style={{ fontFamily: "'Comic Relief', system-ui, sans-serif" }}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
