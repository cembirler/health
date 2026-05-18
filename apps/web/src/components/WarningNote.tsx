// Inline warning glyph + text using the brand `orange-700` token from
// @theme (index.css). Use anywhere a soft warning needs to render — keeps
// the icon, color, and weight defined exactly once.

import { TriangleAlert } from "lucide-react";
import { cn } from "../lib/cn";

export function WarningNote({
  children,
  className,
  iconClassName,
}: {
  children: React.ReactNode;
  className?: string;
  iconClassName?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-1.5 text-warning leading-snug",
        className,
      )}
    >
      <TriangleAlert
        className={cn("h-3.5 w-3.5 flex-shrink-0 mt-0.5", iconClassName)}
        strokeWidth={2.5}
      />
      <div className="min-w-0">{children}</div>
    </div>
  );
}
