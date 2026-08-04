import { forwardRef } from "react";
import type { AnchorHTMLAttributes, ReactNode } from "react";

interface LinkProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  href: string;
  children?: ReactNode;
}

// Stand-in for next/link outside a Next.js router context — renders a plain
// anchor so copied components resolve without edits.
const Link = forwardRef<HTMLAnchorElement, LinkProps>(({ href, children, ...rest }, ref) => (
  <a ref={ref} href={href} {...rest}>
    {children}
  </a>
));
Link.displayName = "Link";

export default Link;
