// Generates the PWA icons: `node scripts/make-icons.mjs`
import { mkdirSync, writeFileSync } from "node:fs";

import { iconPng } from "./icon-png.mjs";

const out = new URL("../public/icons/", import.meta.url);
mkdirSync(out, { recursive: true });
for (const [name, size, safe] of [
  ["icon-192.png", 192, 1],
  ["icon-512.png", 512, 1],
  ["icon-maskable-512.png", 512, 0.8],
  ["apple-touch-icon.png", 180, 0.9],
  ["favicon-32.png", 32, 1],
]) {
  writeFileSync(new URL(name, out), iconPng(size, safe));
}
console.log("icons written");
