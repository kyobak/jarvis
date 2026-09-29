<script lang="ts">
  import { clock } from "../lib/clock.svelte";
  import { app } from "../lib/store.svelte";
  import { countdown, duration, weekdayShort } from "../lib/time";
  import Panel from "./Panel.svelte";

  let { booting = false, delay = 0 }: { booting?: boolean; delay?: number } = $props();

  const today = $derived(duration(app.focus?.today_min ?? 0));
  const week = $derived(app.focus?.week ?? []);
  const maxMin = $derived(Math.max(240, ...week.map((d) => d.min)));
  const session = $derived(app.focus?.session ?? null);
  const sessionProgress = $derived.by(() => {
    if (!session) return 0;
    const total = session.ends_at - session.started_at;
    return Math.min(1, Math.max(0, (clock.now - session.started_at) / total));
  });
  const weekTotal = $derived(duration(week.reduce((s, d) => s + d.min, 0)));
</script>

<Panel title="집중" {booting} {delay}>
  {#snippet meta()}
    이번 주 <span class="num">{weekTotal.h}</span>시간
  {/snippet}

  <div class="row">
    <div class="total">
      <span class="caption">오늘</span>
      <span class="big">
        <span class="num">{today.h}</span><small>시간</small>
        <span class="num">{today.m}</span><small>분</small>
      </span>
    </div>

    <svg class="bars" viewBox="0 0 140 56" aria-label="주간 공부 시간">
      {#each week as d, i}
        {@const h = Math.max(2, (d.min / maxMin) * 40)}
        <rect
          x={i * 20 + 4}
          y={42 - h}
          width="10"
          height={h}
          class:today={i === week.length - 1}
        />
        <text x={i * 20 + 9} y="54">{weekdayShort(d.date)}</text>
      {/each}
    </svg>
  </div>

  {#if session}
    <div class="session">
      <span class="num timer">{countdown(session.ends_at - clock.now)}</span>
      <span class="track"><span class="fill" style:transform="scaleX({sessionProgress})"></span></span>
      <span class="state">{session.paused ? "일시정지" : "집중 모드"}</span>
    </div>
  {/if}
</Panel>

<style>
  .row {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 12px;
  }
  .total {
    display: flex;
    flex-direction: column;
  }
  .caption {
    font-size: 12px;
    color: var(--frost-3);
  }
  .big .num {
    font-size: 30px;
    font-weight: 500;
    line-height: 1.1;
  }
  .big small {
    margin: 0 6px 0 2px;
    font-size: 13px;
    color: var(--frost-2);
  }
  .bars {
    width: 140px;
    height: 56px;
    overflow: visible;
  }
  rect {
    fill: var(--tide);
  }
  rect.today {
    fill: var(--arc);
  }
  text {
    font-size: 9px;
    fill: var(--frost-3);
    text-anchor: middle;
  }
  .session {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 10px;
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid var(--tide-faint);
  }
  .timer {
    font-size: 18px;
    color: var(--arc);
  }
  .track {
    height: 2px;
    background: var(--tide-faint);
  }
  .fill {
    display: block;
    height: 100%;
    background: var(--arc);
    transform-origin: 0 50%;
  }
  .state {
    font-size: 12px;
    color: var(--frost-2);
  }
</style>
