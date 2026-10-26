import { describe, expect, it } from "vitest";

import { backoffMs, supportedCodecs } from "./mse";

describe("MSE player helpers", () => {
  it("offers only codecs the browser supports", () => {
    const list = supportedCodecs((mime) => mime.includes("avc1") || mime.includes("mp4a.40.2"));
    expect(list.split(",")).toContain("avc1.640029");
    expect(list).not.toContain("hvc1");
    expect(list).toContain("mp4a.40.2");
  });

  it("backs off exponentially and caps at 30 s", () => {
    expect([0, 1, 2, 3].map(backoffMs)).toEqual([1000, 2000, 4000, 8000]);
    expect(backoffMs(10)).toBe(30000);
  });
});
