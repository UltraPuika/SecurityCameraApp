import { describe, expect, it } from "vitest";

import en from "./locales/en.json";
import lv from "./locales/lv.json";

type Tree = { [key: string]: string | Tree };

function flatten(tree: Tree, prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  for (const [k, v] of Object.entries(tree)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (typeof v === "string") out.set(key, v);
    else for (const [ck, cv] of flatten(v, key)) out.set(ck, cv);
  }
  return out;
}

const placeholders = (s: string) => [...s.matchAll(/{{\s*(\w+)\s*}}/g)].map((m) => m[1]).sort();

describe("i18n catalogues", () => {
  const enKeys = flatten(en);
  const lvKeys = flatten(lv);

  it("lv has every en key", () => {
    expect([...enKeys.keys()].filter((k) => !lvKeys.has(k))).toEqual([]);
  });

  it("en has every lv key", () => {
    expect([...lvKeys.keys()].filter((k) => !enKeys.has(k))).toEqual([]);
  });

  it("no empty translations", () => {
    const empty = [...enKeys, ...lvKeys].filter(([, v]) => v.trim() === "").map(([k]) => k);
    expect(empty).toEqual([]);
  });

  it("placeholders match between languages", () => {
    const mismatched = [...enKeys.keys()].filter(
      (k) => lvKeys.has(k) && placeholders(enKeys.get(k)!).join() !== placeholders(lvKeys.get(k)!).join(),
    );
    expect(mismatched).toEqual([]);
  });
});
