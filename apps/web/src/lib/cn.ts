// Minimal className combiner — joins truthy strings with spaces. Same role
// as clsx + tailwind-merge, without the deps. We don't need conflict
// resolution because we never override Tailwind classes from the outside
// in this app.
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
