// Dependency-free PNG renderer for the app icon (used by the PWA and Android icon scripts).
import { crc32, deflateSync } from "node:zlib";

const BG = [0x0b, 0x0f, 0x14];
const RING = [0x3f, 0xb6, 0x8b];
const LENS = [0x18, 0x20, 0x2a];
const DOT = [0xd8, 0xe0, 0xea];

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(td) >>> 0);
  return Buffer.concat([len, td, crc]);
}

/**
 * @param {number} size  edge length in px
 * @param {number} safe  fraction of the canvas the artwork may use (maskable/adaptive need less)
 * @param {boolean} transparent  transparent background (Android adaptive foreground layer)
 */
export function iconPng(size, safe = 1, transparent = false) {
  const raw = Buffer.alloc((size * 4 + 1) * size);
  const c = size / 2;
  const r = (size / 2) * safe;
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0;
    for (let x = 0; x < size; x++) {
      const d = Math.hypot(x + 0.5 - c, y + 0.5 - c);
      const dot = Math.hypot(x + 0.5 - (c - r * 0.25), y + 0.5 - (c - r * 0.25));
      let col = BG;
      let alpha = transparent ? 0 : 255;
      if (d < r * 0.82 && d > r * 0.62) {
        col = RING;
        alpha = 255;
      } else if (d <= r * 0.62) {
        col = dot < r * 0.14 ? DOT : LENS;
        alpha = 255;
      }
      const o = y * (size * 4 + 1) + 1 + x * 4;
      raw[o] = col[0];
      raw[o + 1] = col[1];
      raw[o + 2] = col[2];
      raw[o + 3] = alpha;
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}
