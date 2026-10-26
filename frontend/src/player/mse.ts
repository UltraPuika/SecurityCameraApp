/**
 * Minimal MSE player for the backend's go2rtc proxy (fMP4 over WebSocket).
 * Uses ManagedMediaSource on iOS 17.1+ where classic MediaSource is unavailable.
 */

import { liveUrl } from "../api";

export type PlayerState = "connecting" | "playing" | "waiting" | "error" | "stopped";

const CANDIDATE_CODECS = [
  "avc1.640029",
  "avc1.64002A",
  "avc1.640033",
  "avc1.4D401F",
  "avc1.42E01E",
  "hvc1.1.6.L153.B0",
  "hev1.1.6.L153.B0",
  "mp4a.40.2",
  "mp4a.40.5",
  "flac",
  "opus",
];
// Errors where retrying cannot help until the user changes something.
const FATAL = new Set(["auth.not_authenticated", "camera.not_found", "player.mse_unsupported"]);
const MAX_BUFFER_SECONDS = 10;
const STALL_MS = 15000;

type MediaSourceCtor = typeof MediaSource;

function mediaSourceCtor(): MediaSourceCtor | null {
  const w = window as unknown as Record<string, unknown>;
  if (typeof w.ManagedMediaSource === "function") return w.ManagedMediaSource as MediaSourceCtor;
  if (typeof w.MediaSource === "function") return w.MediaSource as MediaSourceCtor;
  return null;
}

export function supportedCodecs(isSupported: (mime: string) => boolean): string {
  return CANDIDATE_CODECS.filter((c) =>
    isSupported(c.startsWith("mp4a") || c === "flac" || c === "opus" ? `audio/mp4; codecs="${c}"` : `video/mp4; codecs="${c}"`),
  ).join(",");
}

export function backoffMs(attempt: number): number {
  return Math.min(30000, 1000 * 2 ** Math.min(attempt, 5));
}

export class MsePlayer {
  private ws: WebSocket | null = null;
  private ms: MediaSource | null = null;
  private sb: SourceBuffer | null = null;
  private queue: ArrayBuffer[] = [];
  private attempt = 0;
  private retryTimer: number | undefined;
  private stallTimer: number | undefined;
  private objectUrl: string | null = null;
  private stopped = true;

  constructor(
    private readonly video: HTMLVideoElement,
    private readonly cameraId: number,
    private readonly quality: "main" | "sub",
    private readonly onState: (state: PlayerState, code?: string, detail?: Record<string, unknown>) => void,
  ) {}

  start(): void {
    this.stopped = false;
    this.attempt = 0;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    window.clearTimeout(this.retryTimer);
    this.teardown();
    this.onState("stopped");
  }

  private connect(): void {
    this.teardown();
    const MS = mediaSourceCtor();
    if (!MS) {
      this.onState("error", "player.mse_unsupported");
      return;
    }
    this.onState("connecting");
    const ms = new MS();
    this.ms = ms;
    this.video.disableRemotePlayback = true;
    if ("ManagedMediaSource" in window && MS !== window.MediaSource) {
      this.video.srcObject = ms as unknown as MediaProvider;
    } else {
      this.objectUrl = URL.createObjectURL(ms);
      this.video.src = this.objectUrl;
    }
    ms.addEventListener("sourceopen", () => this.openSocket(MS), { once: true });
  }

  private openSocket(MS: MediaSourceCtor): void {
    const ws = new WebSocket(liveUrl(this.cameraId, this.quality));
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "mse", value: supportedCodecs((m) => MS.isTypeSupported(m)) }));
      this.armStallTimer();
    };
    ws.onmessage = (ev: MessageEvent<string | ArrayBuffer>) => {
      if (typeof ev.data === "string") {
        this.onText(ev.data);
      } else {
        this.armStallTimer();
        this.queue.push(ev.data);
        this.pump();
      }
    };
    ws.onclose = () => {
      if (this.ws === ws && !this.stopped) this.scheduleRetry();
    };
  }

  private onText(text: string): void {
    let msg: { type?: string; value?: string; code?: string; [k: string]: unknown };
    try {
      msg = JSON.parse(text);
    } catch {
      return;
    }
    if (msg.type === "mse" && msg.value && this.ms) {
      try {
        this.sb = this.ms.addSourceBuffer(msg.value);
        this.sb.mode = "segments";
        this.sb.addEventListener("updateend", () => this.pump());
        this.video.play().catch(() => undefined);
        this.video.addEventListener(
          "playing",
          () => {
            this.attempt = 0;
            this.onState("playing");
          },
          { once: true },
        );
      } catch {
        this.fail("player.codec_unsupported", { mime: msg.value });
      }
    } else if (msg.type === "error") {
      const { code = "stream.upstream_error", ...detail } = msg;
      this.fail(String(code), detail);
    }
  }

  private pump(): void {
    const sb = this.sb;
    if (!sb || sb.updating || this.queue.length === 0) return;
    const buffered = sb.buffered;
    if (buffered.length > 0) {
      const end = buffered.end(buffered.length - 1);
      const start = buffered.start(0);
      if (end - start > MAX_BUFFER_SECONDS) {
        sb.remove(start, end - MAX_BUFFER_SECONDS / 2);
        return;
      }
      // Stay at the live edge if playback fell behind (e.g. after the tab was in the background).
      if (end - this.video.currentTime > 3) this.video.currentTime = end - 0.5;
    }
    const chunk = this.queue.shift()!;
    try {
      sb.appendBuffer(chunk);
    } catch {
      this.fail("player.append_failed");
    }
  }

  private armStallTimer(): void {
    window.clearTimeout(this.stallTimer);
    this.stallTimer = window.setTimeout(() => {
      if (!this.stopped) {
        this.onState("waiting");
        this.scheduleRetry();
      }
    }, STALL_MS);
  }

  private fail(code: string, detail: Record<string, unknown> = {}): void {
    this.onState("error", code, detail);
    if (FATAL.has(code)) {
      this.stopped = true;
      this.teardown();
      return;
    }
    this.scheduleRetry(code === "stream.limit_reached" ? 30000 : undefined);
  }

  private scheduleRetry(delay?: number): void {
    this.teardown();
    window.clearTimeout(this.retryTimer);
    this.retryTimer = window.setTimeout(() => this.connect(), delay ?? backoffMs(this.attempt++));
  }

  private teardown(): void {
    window.clearTimeout(this.stallTimer);
    const ws = this.ws;
    this.ws = null;
    if (ws && ws.readyState <= WebSocket.OPEN) ws.close();
    this.queue = [];
    this.sb = null;
    if (this.ms && this.ms.readyState === "open") {
      try {
        this.ms.endOfStream();
      } catch {
        /* already closed */
      }
    }
    this.ms = null;
    this.video.removeAttribute("src");
    this.video.srcObject = null;
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
    this.objectUrl = null;
  }
}
