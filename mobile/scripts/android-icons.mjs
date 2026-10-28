// Writes launcher + adaptive icons into the generated Android project (run after `cap add android`).
import { mkdirSync, writeFileSync } from "node:fs";

import { iconPng } from "../../frontend/scripts/icon-png.mjs";

const res = new URL("../android/app/src/main/res/", import.meta.url);
const DENSITIES = { mdpi: 1, hdpi: 1.5, xhdpi: 2, xxhdpi: 3, xxxhdpi: 4 };

for (const [name, scale] of Object.entries(DENSITIES)) {
  const dir = new URL(`mipmap-${name}/`, res);
  mkdirSync(dir, { recursive: true });
  const legacy = iconPng(Math.round(48 * scale), 0.92);
  writeFileSync(new URL("ic_launcher.png", dir), legacy);
  writeFileSync(new URL("ic_launcher_round.png", dir), legacy);
  // Adaptive foreground: 108dp canvas, artwork inside the 66dp safe zone.
  writeFileSync(new URL("ic_launcher_foreground.png", dir), iconPng(Math.round(108 * scale), 0.6, true));
}

mkdirSync(new URL("values/", res), { recursive: true });
writeFileSync(
  new URL("values/ic_launcher_background.xml", res),
  '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">#0B0F14</color>\n</resources>\n',
);

writeFileSync(new URL("../www/icon.png", import.meta.url), iconPng(176, 1));
console.log("android icons written");
