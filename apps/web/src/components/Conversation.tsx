// Auto-scrolling conversation container. Small useEffect that sticks the
// scroll to the bottom while new content arrives; user scroll-up disables
// the auto-stick until they scroll back to bottom.

import { useEffect, useRef, useState } from "react";
import { cn } from "../lib/cn";

export function Conversation({
  className,
  children,
  scrollSignal,
}: {
  className?: string;
  children: React.ReactNode;
  // Bumping this number triggers a scroll-to-bottom from the parent
  // (e.g., new message arrived) only when the user is already at bottom.
  scrollSignal: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onScroll = () => {
      const slack = 8; // px
      setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < slack);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el || !atBottom) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [scrollSignal, atBottom]);

  return (
    <div
      ref={ref}
      className={cn("relative flex-1 overflow-y-auto", className)}
      role="log"
    >
      <div className="p-4">{children}</div>
    </div>
  );
}
