// src/lib/text.ts
export function stripMarkdown(text: string | null | undefined): string {
  if (!text) return "";
  return text
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1") // [text](url) → text
    .replace(/[*_~`#>]+/g, "") // remove emphasis/heading chars
    .replace(/\n+/g, " ") // collapse newlines
    .trim();
}
