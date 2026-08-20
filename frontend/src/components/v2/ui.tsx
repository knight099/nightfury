"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Shared V2 primitives.
 *
 * The V2 shell speaks oklch tokens; V1 speaks hex. These wrappers exist so the
 * pages ported over from V1 don't each re-derive the palette by hand and drift
 * apart. Keep the token values here and nowhere else.
 */

export const V2 = {
  ground: "oklch(9% 0.015 265)",
  panel: "oklch(12% 0.015 265)",
  raised: "oklch(15% 0.015 265)",
  border: "oklch(22% 0.015 265)",
  borderSubtle: "oklch(19% 0.015 265)",
  ink: "oklch(97% 0.005 265)",
  muted: "oklch(72% 0.01 265)",
  dim: "oklch(55% 0.01 265)",
  amber: "oklch(85% 0.16 84)",
  green: "oklch(79.2% 0.209 151.711)",
  red: "oklch(70.4% 0.191 22.216)",
} as const;

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 mb-6">
      <div>
        <div className="text-[28px] font-bold tracking-tight">{title}</div>
        {subtitle && (
          <div className="text-[13px] text-[oklch(55%_0.01_265)] mt-1.5 max-w-[62ch] leading-relaxed">
            {subtitle}
          </div>
        )}
      </div>
      {action}
    </div>
  );
}

export function Page({ children, wide }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={cn("mx-auto px-12 pt-12 pb-20", wide ? "max-w-[1400px]" : "max-w-[1040px]")}>
      {children}
    </div>
  );
}

export function Card({
  children,
  className,
  padded = true,
}: {
  children: React.ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <div
      className={cn(
        "bg-[oklch(12%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-[14px]",
        padded && "p-5",
        className
      )}
    >
      {children}
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="p-6 text-sm text-center text-[oklch(70.4%_0.191_22.216)] border border-[oklch(70.4%_0.191_22.216)] rounded-[14px] bg-[oklch(18%_0.2_22)]">
      {message}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="p-10 text-center border border-[oklch(22%_0.015_265)] rounded-[14px] bg-[oklch(12%_0.015_265)]">
      <div className="text-[15px] text-[oklch(72%_0.01_265)]">{title}</div>
      {hint && <div className="text-[12.5px] text-[oklch(55%_0.01_265)] mt-2">{hint}</div>}
    </div>
  );
}

type BtnVariant = "primary" | "ghost" | "danger";

export function Btn({
  variant = "ghost",
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant }) {
  const styles: Record<BtnVariant, string> = {
    primary:
      "bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)] hover:bg-[oklch(89%_0.16_84)] font-semibold",
    ghost:
      "bg-[oklch(15%_0.015_265)] text-[oklch(85%_0.005_265)] border border-[oklch(24%_0.02_265)] hover:bg-[oklch(18%_0.015_265)]",
    danger:
      "bg-[oklch(70.4%_0.191_22.216)]/10 text-[oklch(70.4%_0.191_22.216)] border border-[oklch(70.4%_0.191_22.216)]/25 hover:bg-[oklch(70.4%_0.191_22.216)]/20",
  };
  return (
    <button
      {...props}
      className={cn(
        "text-[12.5px] px-3 py-1.5 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
        styles[variant],
        className
      )}
    />
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="block text-[11px] uppercase tracking-[0.04em] text-[oklch(55%_0.01_265)] mb-1.5">
        {label}
      </span>
      {children}
    </label>
  );
}

export const inputClass =
  "w-full px-3 py-2 text-[13px] bg-[oklch(15%_0.015_265)] border border-[oklch(24%_0.02_265)] rounded-md text-[oklch(97%_0.005_265)] focus:outline-none focus:border-[oklch(85%_0.16_84)] transition-colors";

export function BackLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-1.5 text-[12.5px] text-[oklch(55%_0.01_265)] hover:text-[oklch(97%_0.005_265)] transition-colors mb-5"
    >
      <ArrowLeft size={14} /> {label}
    </Link>
  );
}

export function Pill({ tone, children }: { tone: "green" | "amber" | "red" | "neutral"; children: React.ReactNode }) {
  const color =
    tone === "green" ? V2.green : tone === "amber" ? V2.amber : tone === "red" ? V2.red : V2.dim;
  return (
    <span
      className="inline-block text-[11px] font-bold tracking-wide px-2.5 py-1 rounded-full whitespace-nowrap"
      style={{ color, backgroundColor: `color-mix(in oklab, ${color} 16%, transparent)` }}
    >
      {children}
    </span>
  );
}
