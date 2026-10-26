import { describe, expect, it } from "vitest";

import { detectLanguage } from "./detect";

describe("detectLanguage", () => {
  it("picks Latvian for any lv locale", () => {
    expect(detectLanguage(["lv-LV", "en-US"])).toBe("lv");
    expect(detectLanguage(["en-GB", "LV"])).toBe("lv");
  });

  it("falls back to English otherwise", () => {
    expect(detectLanguage(["de-DE", "ru"])).toBe("en");
    expect(detectLanguage([])).toBe("en");
  });
});
