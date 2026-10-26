export const LANGUAGES = ["lv", "en"] as const;
export type Language = (typeof LANGUAGES)[number];

export function detectLanguage(preferred: readonly string[]): Language {
  return preferred.some((l) => l.toLowerCase().startsWith("lv")) ? "lv" : "en";
}
