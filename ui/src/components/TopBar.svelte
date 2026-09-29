<script lang="ts">
  import { clock } from "../lib/clock.svelte";
  import { app } from "../lib/store.svelte";
  import { koreanDate, pad } from "../lib/time";
  import type { LinkState } from "../lib/types";

  let { booting = false }: { booting?: boolean } = $props();

  const now = $derived(new Date(clock.now));

  type Tone = "ok" | "off" | "warn" | "bad";
  const tone = (s: LinkState | string | undefined): Tone =>
    s === "ok" || s === "mock" || s === "on"
      ? "ok"
      : s === "offline" || s === "expired" || s === "paused"
        ? "warn"
        : s === "error"
          ? "bad"
          : "off";

  const chips = $derived.by(() => {
    const st = app.status;
    if (!st) return [];
    const i = st.integrations;
    return [
      { label: "카메라", tone: tone(st.camera) },
      { label: "마이크", tone: tone(st.mic) },
      { label: "캘린더", tone: tone(i.calendar) },
      { label: "Gmail", tone: tone(i.gmail) },
      { label: "Slack", tone: tone(i.slack) },
      { label: "Spotify", tone: tone(i.spotify) },
      { label: "Claude", tone: tone(i.claude) },
    ];
  });

  const drowsy = $derived(app.drowsiness);
</script>

<header class="top" class:booting>
  <div class="clock">
    <span class="hm num">{pad(now.getHours())}<span class="colon">:</span>{pad(now.getMinutes())}</span>
    <span class="sec num">{pad(now.getSeconds())}</span>
    <span class="date">{koreanDate(now)}</span>
  </div>

  <div class="status">
    {#if !app.connected && app.everConnected}
      <span class="server-down">서버 연결 끊김 · 재연결 중</span>
    {/if}
    {#if app.status?.mock}
      <span class="mock">모의 모드</span>
    {/if}
    {#if drowsy?.enabled}
      <span class="drowsy" title="졸음 지수">
        졸음
        <span class="gauge"><span style:transform="scaleX({Math.min(1, drowsy.score)})"></span></span>
      </span>
    {/if}
    {#each chips as c}
      <span class="chip {c.tone}"><i></i>{c.label}</span>
    {/each}
  </div>
</header>

<style>
  .top {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    padding-bottom: 14px;
    border-bottom: 1px solid var(--tide-faint);
  }
  .clock {
    display: flex;
    align-items: baseline;
    gap: 10px;
  }
  .hm {
    font-size: 46px;
    font-weight: 500;
    line-height: 1;
    letter-spacing: 0.04em;
  }
  .colon {
    margin: 0 1px;
    color: var(--arc);
  }
  .sec {
    font-size: 17px;
    color: var(--tide);
    width: 22px;
  }
  .date {
    margin-left: 6px;
    font-size: 16px;
    color: var(--frost-2);
  }
  .status {
    display: flex;
    align-items: center;
    gap: 16px;
    font-size: 12.5px;
    color: var(--frost-2);
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .chip i {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--tide);
  }
  .chip.ok i {
    background: var(--arc);
  }
  .chip.warn i {
    background: var(--ember);
  }
  .chip.warn {
    color: var(--ember);
  }
  .chip.bad i {
    background: var(--flare);
  }
  .chip.off {
    color: var(--frost-3);
  }
  .mock {
    padding: 1px 8px;
    border: 1px solid var(--tide-line);
    color: var(--frost-3);
  }
  .server-down {
    color: var(--flare);
  }
  .drowsy {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .gauge {
    position: relative;
    width: 44px;
    height: 3px;
    background: var(--tide-faint);
  }
  .gauge span {
    position: absolute;
    inset: 0;
    background: var(--arc);
    transform-origin: 0 50%;
    transition: transform 1.5s linear;
  }
  .booting {
    opacity: 0;
    animation: fade 0.6s ease-out 0.25s forwards;
  }
  @keyframes fade {
    to {
      opacity: 1;
    }
  }
</style>
