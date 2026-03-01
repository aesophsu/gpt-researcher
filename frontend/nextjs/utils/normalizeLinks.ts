export function normalizeLegacyLinkLabels(text: string): string {
  if (!text) return text;
  return text.replace(/\[url website\]\(([^)]+)\)/gi, "[source link]($1)");
}
