// Top site header — brand mark + nav. Used by every React route.

import { Link, useLocation } from "react-router-dom";
import { HeartPulse } from "lucide-react";
import { cn } from "../lib/cn";

const NAV: Array<{ href: string; label: string }> = [
  { href: "/", label: "Home" },
  { href: "/chat", label: "Chat" },
  { href: "/writeup", label: "Writeup" },
];

export function SiteHeader() {
  const { pathname } = useLocation();

  return (
    <header className="sticky top-0 z-10 flex items-center justify-between border-b border-gray-200 bg-white px-6 py-3">
      <div className="flex items-center gap-2.5 text-base leading-none text-blue-900 font-medium">
        <span className="grid h-7 w-7 place-items-center rounded-md bg-blue-900 text-white">
          <HeartPulse className="h-4 w-4" />
        </span>
        <span>Health Price Transparency</span>
      </div>

      <nav className="flex gap-1">
        {NAV.map((item) => {
          // /chat/:sessionId pages highlight the "Chat" tab.
          const active =
            pathname === item.href ||
            (item.href === "/chat" && pathname.startsWith("/chat/"));
          const className = cn(
            "rounded-md px-3 py-1.5 text-base leading-none font-medium transition-colors text-blue-900",
            active ? "bg-blue-900/15 font-semibold" : "hover:bg-blue-900/10",
          );
          return (
            <Link key={item.href} to={item.href} className={className}>
              {item.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
