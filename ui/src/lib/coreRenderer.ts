// Canvas 2D renderer for the central core. No WebGL, no filters: glow comes from
// pre-rendered radial-gradient sprites, and frames are capped (30 fps max).

import type { CoreState } from "./types";

type RGB = [number, number, number];

const PALETTE = {
  arc: [92, 225, 255] as RGB,
  ember: [255, 181, 71] as RGB,
  flare: [255, 77, 94] as RGB,
  tide: [30, 90, 115] as RGB,
};
type Tone = keyof typeof PALETTE;

const TAU = Math.PI * 2;
const BAR_COUNT = 72;

function rgba([r, g, b]: RGB, a: number): string {
  return `rgba(${r | 0},${g | 0},${b | 0},${a.toFixed(3)})`;
}

function mix(a: RGB, b: RGB, t: number): RGB {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

function approach(current: number, target: number, rate: number, dt: number): number {
  return current + (target - current) * (1 - Math.exp(-rate * dt));
}

function makeSprite(size: number, color: RGB, stops: [number, number][]): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = c.height = Math.max(2, Math.ceil(size));
  const g = c.getContext("2d")!;
  const r = c.width / 2;
  const grad = g.createRadialGradient(r, r, 0, r, r, r);
  for (const [offset, alpha] of stops) grad.addColorStop(offset, rgba(color, alpha));
  g.fillStyle = grad;
  g.fillRect(0, 0, c.width, c.height);
  return c;
}

interface Sprites {
  glow: HTMLCanvasElement;
  heart: HTMLCanvasElement;
}

export class CoreRenderer {
  private ctx: CanvasRenderingContext2D;
  private size = 0;
  private dpr = 1;
  private sprites = new Map<Tone, Sprites>();

  private state: CoreState = "idle";
  private alertLevel = 1;
  private tone: Tone = "arc";
  private prevTone: Tone = "arc";
  private toneMix = 1;
  private color: RGB = [...PALETTE.arc];

  private t = 0;
  private spin = 0;
  private energy = 1; // overall brightness, dims when offline
  private level = 0;
  private bars = new Float32Array(BAR_COUNT);
  private thinkBlend = 0;
  private listenBlend = 0;
  private speakBlend = 0;
  private boot = 0; // 0 → 1 ignition progress
  private bootStart = -1;

  constructor(private canvas: HTMLCanvasElement, private reducedMotion: boolean) {
    this.ctx = canvas.getContext("2d")!;
    if (reducedMotion) this.boot = 1;
  }

  resize(cssSize: number): void {
    this.dpr = Math.min(2, window.devicePixelRatio || 1);
    this.size = cssSize;
    this.canvas.width = Math.round(cssSize * this.dpr);
    this.canvas.height = Math.round(cssSize * this.dpr);
    this.canvas.style.width = this.canvas.style.height = `${cssSize}px`;
    this.sprites.clear();
  }

  startBoot(delayMs: number): void {
    if (this.reducedMotion) return;
    this.boot = 0;
    this.bootStart = this.t + delayMs / 1000;
  }

  setState(state: CoreState, alertLevel = 1): void {
    this.state = state;
    this.alertLevel = alertLevel;
    const tone: Tone =
      state === "offline" ? "tide" : state === "alert" ? (alertLevel >= 2 ? "flare" : "ember") : "arc";
    if (tone !== this.tone) {
      this.prevTone = this.tone;
      this.tone = tone;
      this.toneMix = 0;
    }
  }

  private spritesFor(tone: Tone): Sprites {
    let s = this.sprites.get(tone);
    if (!s) {
      const px = this.size * this.dpr;
      const c = PALETTE[tone];
      s = {
        glow: makeSprite(px, c, [[0, 0.34], [0.3, 0.16], [0.6, 0.05], [1, 0]]),
        heart: makeSprite(px * 0.4, c, [[0, 0.95], [0.18, 0.85], [0.45, 0.35], [0.75, 0.08], [1, 0]]),
      };
      this.sprites.set(tone, s);
    }
    return s;
  }

  /** Advance by `dt` seconds and draw. `inputLevel` is the latest mic/TTS level (0..1). */
  frame(dt: number, inputLevel: number): void {
    const { ctx, size, dpr } = this;
    if (!size) return;
    this.t += dt;
    const st = this.state;
    const motion = this.reducedMotion ? 0 : 1;

    if (this.bootStart >= 0 && this.t >= this.bootStart) {
      this.boot = Math.min(1, (this.t - this.bootStart) / 1.6);
      if (this.boot >= 1) this.bootStart = -1;
    }
    const boot = this.boot;
    const ease = (x: number) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);

    this.toneMix = Math.min(1, this.toneMix + dt / 0.6);
    this.color = mix(PALETTE[this.prevTone], PALETTE[this.tone], this.toneMix);
    this.energy = approach(this.energy, st === "offline" ? 0.35 : 1, 3, dt);
    this.level = approach(this.level, inputLevel, 14, dt);
    this.thinkBlend = approach(this.thinkBlend, st === "thinking" ? 1 : 0, 5, dt);
    this.listenBlend = approach(this.listenBlend, st === "listening" ? 1 : 0, 6, dt);
    this.speakBlend = approach(this.speakBlend, st === "speaking" ? 1 : 0, 6, dt);

    const spinRate = st === "offline" ? 0 : st === "thinking" ? 0.9 : 0.05;
    this.spin += dt * spinRate * motion;

    const R = size / 2;
    const color = this.color;
    const e = this.energy;
    const breath = 0.5 + 0.5 * Math.sin((this.t * TAU) / 4) * motion; // 4 s cycle

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size, size);
    ctx.translate(R, R);

    // Glow sprites, cross-faded between tones.
    const glowScale = ease(boot * 1.4 - 0.2);
    if (glowScale > 0) {
      const drawGlow = (tone: Tone, alpha: number) => {
        if (alpha <= 0.01) return;
        const sp = this.spritesFor(tone);
        const alertPulse = st === "alert" ? 0.25 * (0.5 + 0.5 * Math.sin(this.t * (this.alertLevel >= 2 ? 12 : 6))) : 0;
        ctx.globalAlpha = alpha * e * (0.62 + 0.28 * breath + alertPulse + this.level * 0.3) * glowScale;
        const gs = size * (0.98 + this.level * 0.05) * glowScale;
        ctx.drawImage(sp.glow, -gs / 2, -gs / 2, gs, gs);
      };
      drawGlow(this.prevTone, 1 - this.toneMix);
      drawGlow(this.tone, this.toneMix);
      ctx.globalAlpha = 1;
    }

    ctx.lineCap = "round";

    // Outer tick ring with cardinal labels.
    const tickP = ease(boot * 2 - 0.3);
    if (tickP > 0) {
      const r = R * 0.9;
      ctx.save();
      ctx.rotate(this.spin * 0.25);
      ctx.beginPath();
      const ticks = 120;
      const shown = Math.floor(ticks * tickP);
      for (let i = 0; i < shown; i++) {
        const a = (i / ticks) * TAU;
        const len = i % 10 === 0 ? 9 : i % 5 === 0 ? 5 : 2.5;
        const c = Math.cos(a);
        const s = Math.sin(a);
        ctx.moveTo(c * r, s * r);
        ctx.lineTo(c * (r - len), s * (r - len));
      }
      ctx.strokeStyle = rgba(color, 0.42 * e);
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.restore();

      ctx.beginPath();
      ctx.arc(0, 0, R * 0.955, 0, TAU * tickP);
      ctx.strokeStyle = rgba(color, 0.14 * e);
      ctx.stroke();
    }

    // Segmented ring: slow drift at rest; splits into three counter-rotating rings while thinking.
    const segP = ease(boot * 2 - 0.6);
    if (segP > 0) {
      const tb = this.thinkBlend;
      const rings = [
        { r: 0.74, w: 2.4, speed: 1, segs: [[0, 0.2], [0.29, 0.4], [0.52, 0.8]] },
        { r: 0.74 - 0.07 * tb, w: 1.6, speed: -1.7, segs: [[0.1, 0.18], [0.45, 0.62], [0.75, 0.83]] },
        { r: 0.74 - 0.13 * tb, w: 1.2, speed: 2.6, segs: [[0.05, 0.3], [0.55, 0.7]] },
      ];
      rings.forEach((ring, idx) => {
        const alpha = idx === 0 ? 0.75 : 0.6 * tb;
        if (alpha < 0.02) return;
        ctx.save();
        ctx.rotate(this.spin * ring.speed + idx * 0.7);
        ctx.beginPath();
        for (const [a0, a1] of ring.segs) {
          ctx.moveTo(Math.cos(a0 * TAU) * R * ring.r, Math.sin(a0 * TAU) * R * ring.r);
          ctx.arc(0, 0, R * ring.r, a0 * TAU, (a0 + (a1 - a0) * segP) * TAU);
        }
        ctx.strokeStyle = rgba(color, alpha * e);
        ctx.lineWidth = ring.w;
        ctx.stroke();
        ctx.restore();
      });
    }

    // Inner ring; swells with the mic level while listening.
    const innerP = ease(boot * 2 - 0.9);
    const innerR = R * (0.5 + 0.05 * this.listenBlend * this.level);
    if (innerP > 0) {
      ctx.beginPath();
      ctx.arc(0, 0, innerR, -Math.PI / 2, -Math.PI / 2 + TAU * innerP);
      ctx.strokeStyle = rgba(color, (0.55 + 0.25 * breath) * e);
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    // Listening: radial bars driven by the input level.
    if (this.listenBlend > 0.02) {
      ctx.beginPath();
      for (let i = 0; i < BAR_COUNT; i++) {
        const a = (i / BAR_COUNT) * TAU - Math.PI / 2;
        const jitter = 0.55 + 0.45 * Math.sin(i * 1.7 + this.t * 9) * Math.sin(i * 0.53 - this.t * 4);
        const target = this.level * Math.abs(jitter);
        this.bars[i] = approach(this.bars[i], target, 18, dt);
        const len = 3 + this.bars[i] * R * 0.16;
        const r0 = innerR + 5;
        ctx.moveTo(Math.cos(a) * r0, Math.sin(a) * r0);
        ctx.lineTo(Math.cos(a) * (r0 + len), Math.sin(a) * (r0 + len));
      }
      ctx.strokeStyle = rgba(color, 0.8 * this.listenBlend * e);
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // Speaking: two phase-shifted polar waveforms synced to the TTS level.
    if (this.speakBlend > 0.02) {
      const amp = R * 0.06 * (0.25 + this.level) * this.speakBlend;
      const base = R * 0.58;
      for (const [k, alpha, ph] of [[6, 0.85, 0], [9, 0.4, 1.9]] as const) {
        ctx.beginPath();
        const steps = 120;
        for (let i = 0; i <= steps; i++) {
          const a = (i / steps) * TAU;
          const w =
            Math.sin(a * k + this.t * 5 + ph) * 0.6 +
            Math.sin(a * (k + 3) - this.t * 7.3 + ph) * 0.4;
          const r = base + w * amp;
          const x = Math.cos(a) * r;
          const y = Math.sin(a) * r;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = rgba(color, alpha * this.speakBlend * e);
        ctx.lineWidth = 1.4;
        ctx.stroke();
      }
    }

    // Alert: sonar ping expanding outward.
    if (st === "alert" && motion) {
      const period = this.alertLevel >= 2 ? 0.7 : 1.4;
      for (let k = 0; k < 2; k++) {
        const p = ((this.t / period + k * 0.5) % 1 + 1) % 1;
        ctx.beginPath();
        ctx.arc(0, 0, R * (0.42 + 0.5 * p), 0, TAU);
        ctx.strokeStyle = rgba(color, (1 - p) * 0.55);
        ctx.lineWidth = 2 * (1 - p) + 0.5;
        ctx.stroke();
      }
    }

    // Heart: bright core sprite with notched inner rings.
    const heartP = ease(boot * 2.2 - 1.1);
    if (heartP > 0) {
      const hs = R * 0.8 * heartP * (1 + 0.035 * breath + 0.08 * this.level);
      const drawHeart = (tone: Tone, alpha: number) => {
        if (alpha <= 0.01) return;
        ctx.globalAlpha = alpha * (0.35 + 0.65 * e);
        ctx.drawImage(this.spritesFor(tone).heart, -hs / 2, -hs / 2, hs, hs);
      };
      drawHeart(this.prevTone, 1 - this.toneMix);
      drawHeart(this.tone, this.toneMix);
      ctx.globalAlpha = 1;

      ctx.save();
      ctx.rotate(-this.spin * 0.8);
      ctx.beginPath();
      const notchR = R * 0.24 * heartP;
      for (let i = 0; i < 6; i++) {
        const a0 = (i / 6) * TAU + 0.08;
        ctx.moveTo(Math.cos(a0) * notchR, Math.sin(a0) * notchR);
        ctx.arc(0, 0, notchR, a0, a0 + TAU / 6 - 0.16);
      }
      ctx.strokeStyle = rgba(color, 0.7 * e);
      ctx.lineWidth = 1.2;
      ctx.stroke();
      ctx.restore();

      ctx.beginPath();
      ctx.arc(0, 0, R * 0.075 * heartP, 0, TAU);
      ctx.fillStyle = `rgba(235,252,255,${(0.75 + 0.25 * breath) * e})`;
      ctx.fill();
    }
  }
}
