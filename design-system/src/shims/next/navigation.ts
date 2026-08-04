// Stand-in for next/navigation outside a Next.js router context.
export function usePathname(): string {
  return "/dashboard";
}

export function useRouter() {
  return {
    push: (_href: string) => {},
    replace: (_href: string) => {},
    back: () => {},
    forward: () => {},
    refresh: () => {},
    prefetch: async (_href: string) => {},
  };
}
