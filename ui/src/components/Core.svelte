<script lang="ts">
  import { onMount } from "svelte";
  import { clock } from "../lib/clock.svelte";
  import { CoreRenderer } from "../lib/coreRenderer";
  import { app, audio, send, visibleCore } from "../lib/store.svelte";
  import { countdown, duration, minutesUntil } from "../lib/time";
  import type { CoreState } from "../lib/types";

  let { bootDelay = 0 }: { bootDelay?: number } = $props();

  let host: HTMLDivElement;
  let canvas: HTMLCanvasElement;
  let renderer: CoreRenderer | undefined;
  let size = $state(440);

  const LABELS: Record<CoreState, string> = {
    idle: "대기 중",
    listening: "듣고 있어요",
    thinking: "생각하는 중",
    speaking: "말하는 중",
    alert: "알림",
    offline: "연결 끊김",
  };

  const core = $derived(visibleCore());

  $effect(() => {
    // Read reactive values before touching the (non-reactive) renderer so the
    // effect always tracks them, even on the first run before mount.
    const state = core;
    const level = app.alert?.level ?? 1;
    renderer?.setState(state, level);
  });

  const nextEvent = $derived.by(() => {
    const events = app.schedule?.events ?? [];
    return events.find((e) => Date.parse(e.start) > clock.now) ?? null;
  });

  const nextIn = $derived(nextEvent ? duration(minutesUntil(nextEvent.start, clock.now)) : null);

  const session = $derived(app.focus?.session ?? null);
  const usagePct = $derived.by(() => {
    const llm = app.status?.llm;
    return llm && llm.limit ? Math.min(100, Math.round((llm.tokens / llm.limit) * 100)) : null;
  });

  function pttDown(): void {
    send("ptt", { down: true });
  }
  function pttUp(): void {
    send("ptt", { down: false });
  }

  onMount(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    renderer = new CoreRenderer(canvas, reduced);
    renderer.setState(core, app.alert?.level ?? 1);

    const fit = () => {
      const rect = host.getBoundingClientRect();
      size = Math.floor(Math.max(260, Math.min(rect.width * 0.94, rect.height - 130, 580)));
      renderer!.resize(size);
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(host);
    renderer.startBoot(bootDelay);

    // Frame cap: 30 fps while active, 20 fps at rest, 2 fps with reduced motion.
    let raf = 0;
    let last = performance.now();
    let acc = 0;
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const current = visibleCore();
      const fps = reduced ? 2 : current === "idle" || current === "offline" ? 20 : 30;
      acc += now - last;
      last = now;
      if (acc < 1000 / fps - 1) return;
      const dt = Math.min(0.1, acc / 1000);
      acc = 0;
      renderer!.frame(dt, audio.level);
    };
    raf = requestAnimationFrame(loop);

    const onVisibility = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden) {
        last = performance.now();
        raf = requestAnimationFrame(loop);
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  });
</script>

<div class="core-zone" bind:this={host}>
  <div class="stage" style:width="{size}px" style:height="{size}px">
    <canvas bind:this={canvas} aria-hidden="true"></canvas>
  </div>

  <div class="instruments" style:width="{Math.min(size + 80, 640)}px">
    <div class="readout left">
      <span class="k">다음 일정</span>
      {#if nextEvent && nextIn}
        <span class="v">
          {#if nextIn.h}<span class="num">{nextIn.h}</span><small>시간</small>{/if}
          <span class="num">{nextIn.m}</span><small>분 후</small>
        </span>
        <span class="sub ellipsis">{nextEvent.title}</span>
      {:else}
        <span class="v num dim">--:--</span>
        <span class="sub">남은 일정 없음</span>
      {/if}
    </div>

    <div class="state" data-state={core}>
      <span class="label">{LABELS[core]}</span>
      {#if core === "offline"}
        <span class="hint">서버에 다시 연결하는 중…</span>
      {:else if core === "idle"}
        <span class="hint">“헤이 자비스” 또는 스페이스 길게</span>
      {/if}
      <button
        class="mic"
        class:live={core === "listening"}
        aria-label="말하기"
        onpointerdown={pttDown}
        onpointerup={pttUp}
        onpointerleave={pttUp}
      >
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <rect x="9" y="3" width="6" height="11" rx="3" fill="none" stroke="currentColor" stroke-width="1.5" />
          <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" fill="none" stroke="currentColor" stroke-width="1.5" />
        </svg>
      </button>
    </div>

    <div class="readout right">
      {#if session}
        <span class="k">집중</span>
        <span class="v num">{countdown(session.ends_at - clock.now)}</span>
        <span class="sub">{session.paused ? "일시정지" : `${session.planned_min}분 세션`}</span>
      {:else}
        <span class="k">AI 사용량</span>
        <span class="v num">{usagePct ?? "--"}<small>%</small></span>
        <span class="sub">오늘 {app.status?.llm.calls ?? 0}회 호출</span>
      {/if}
    </div>
  </div>
</div>

<style>
  .core-zone {
    position: relative;
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }

  canvas {
    display: block;
  }

  .instruments {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: start;
    gap: 24px;
    margin-top: -8px;
  }

  .readout {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
    padding-top: 10px;
  }
  .readout::before {
    content: "";
    position: absolute;
    top: 0;
    width: 36px;
    height: 1px;
    background: var(--tide-line);
  }
  .readout.left {
    align-items: flex-end;
    text-align: right;
  }
  .readout.left::before { right: 0; }
  .readout.right::before { left: 0; }

  .k {
    font-size: 12px;
    color: var(--frost-3);
  }
  .v {
    font-size: 28px;
    font-weight: 500;
    line-height: 1.1;
    color: var(--frost);
  }
  .v small {
    font-size: 14px;
    margin: 0 4px 0 2px;
    color: var(--frost-2);
  }
  .v small:last-child {
    margin-right: 0;
  }
  .v.dim { color: var(--tide); }
  .sub {
    max-width: 100%;
    font-size: 13px;
    color: var(--frost-2);
  }

  .state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
    min-width: 190px;
  }
  .label {
    font-size: 18px;
    font-weight: 500;
    letter-spacing: 0.02em;
    color: var(--arc);
    transition: color 0.4s;
  }
  .state[data-state="alert"] .label { color: var(--ember); }
  .state[data-state="offline"] .label { color: var(--tide); }
  .hint {
    font-size: 12.5px;
    color: var(--frost-3);
  }

  .mic {
    display: grid;
    place-items: center;
    width: 34px;
    height: 34px;
    margin-top: 8px;
    border-radius: 50%;
    border: 1px solid var(--tide-line);
    color: var(--frost-2);
    transition: border-color 0.2s, color 0.2s;
  }
  .mic:hover,
  .mic.live {
    border-color: var(--arc);
    color: var(--arc);
  }
</style>
