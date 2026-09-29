<script lang="ts">
  import { clock } from "../lib/clock.svelte";
  import { app } from "../lib/store.svelte";
  import { hhmm, minutesUntil } from "../lib/time";
  import Panel from "./Panel.svelte";

  let { booting = false, delay = 0 }: { booting?: boolean; delay?: number } = $props();

  const PRE_ALERT_MIN = 10;

  type Row =
    | { kind: "event"; id: string; time: string; title: string; phase: "past" | "now" | "soon" | "later"; note: string }
    | { kind: "now"; time: string };

  const rows = $derived.by((): Row[] => {
    const now = clock.now;
    const all = [...(app.schedule?.events ?? [])].sort((a, b) => Date.parse(a.start) - Date.parse(b.start));
    const out: Row[] = all
      .filter((e) => e.all_day)
      .map((e) => ({ kind: "event" as const, id: e.id, time: "종일", title: e.title, phase: "later" as const, note: "" }));
    const events = all.filter((e) => !e.all_day);
    let markerPlaced = false;
    // Keep the most recent past event for context, then everything ahead.
    const firstFuture = events.findIndex((e) => Date.parse(e.end) > now || Date.parse(e.start) > now);
    const start = firstFuture === -1 ? Math.max(0, events.length - 1) : Math.max(0, firstFuture - 1);
    for (const e of events.slice(start, start + 6)) {
      const s = Date.parse(e.start);
      const end = Date.parse(e.end);
      if (!markerPlaced && s > now) {
        out.push({ kind: "now", time: hhmm(new Date(now)) });
        markerPlaced = true;
      }
      const until = minutesUntil(e.start, now);
      const phase = s <= now && end > now ? "now" : end <= now && s < now ? "past" : until <= PRE_ALERT_MIN ? "soon" : "later";
      const note =
        phase === "now" ? "진행 중" : phase === "soon" ? `${until}분 후` : end === s && phase !== "past" ? "마감" : "";
      out.push({ kind: "event", id: e.id, time: hhmm(new Date(s)), title: e.title, phase, note });
    }
    if (!markerPlaced) out.push({ kind: "now", time: hhmm(new Date(now)) });
    return out;
  });

  const offline = $derived(app.schedule?.offline ?? false);
  const link = $derived(app.status?.integrations.calendar);
  const disabled = $derived(link === "disabled");
  const expired = $derived(link === "expired");
</script>

<Panel title="오늘 일정" tone={offline ? "warn" : "normal"} {booting} {delay} grow>
  {#snippet meta()}
    {#if offline}
      <span class="warn">오프라인 · 캐시 표시 중</span>
    {:else}
      <span class="num">{app.schedule?.events.length ?? 0}</span>개
    {/if}
  {/snippet}

  {#if expired}
    <div class="reauth">
      <span>Google 캘린더 {app.schedule?.synced_at ? "다시 " : ""}연결 필요</span>
      <a class="btn" href="/auth/google" target="_blank">연결하기</a>
    </div>
  {/if}
  {#if disabled}
    <p class="empty">캘린더가 연결되지 않았어요.<br /><a href="/auth/google" target="_blank">연결 방법 보기</a></p>
  {:else}
    <ol class="timeline">
      {#each rows as row (row.kind === "now" ? "now" : row.id)}
        {#if row.kind === "now"}
          <li class="now-line">
            <span class="time num">{row.time}</span>
            <span class="marker"></span>
            <span class="now-label">지금</span>
          </li>
        {:else}
          <li class="event {row.phase}">
            <span class="time num">{row.time}</span>
            <span class="dot"></span>
            <span class="title ellipsis">{row.title}</span>
            {#if row.note}<span class="note">{row.note}</span>{/if}
          </li>
        {/if}
      {/each}
    </ol>
  {/if}
</Panel>

<style>
  .timeline {
    position: relative;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .timeline::before {
    content: "";
    position: absolute;
    left: 55px;
    top: 6px;
    bottom: 6px;
    width: 1px;
    background: var(--tide-faint);
  }
  li {
    position: relative;
    display: grid;
    grid-template-columns: 44px 22px 1fr auto;
    align-items: center;
    min-height: 32px;
  }
  .time {
    font-size: 14px;
    color: var(--frost-2);
  }
  .dot {
    justify-self: center;
    width: 7px;
    height: 7px;
    border: 1px solid var(--tide);
    background: var(--abyss);
    transform: rotate(45deg);
  }
  .title {
    font-size: 14.5px;
  }
  .note {
    margin-left: 8px;
    font-size: 12px;
    color: var(--frost-3);
  }

  .past .time,
  .past .title {
    color: var(--frost-3);
    opacity: 0.7;
  }
  .now .dot {
    border-color: var(--arc);
    background: var(--arc);
  }
  .now .note {
    color: var(--arc);
  }
  .soon .dot {
    border-color: var(--ember);
  }
  .soon .title,
  .soon .note {
    color: var(--ember);
  }

  .now-line {
    min-height: 26px;
  }
  .now-line .time {
    color: var(--arc);
    font-size: 12px;
  }
  .now-line .marker {
    grid-column: 2 / 4;
    height: 1px;
    background: linear-gradient(90deg, var(--arc), rgba(92, 225, 255, 0));
  }
  .now-line .marker::before {
    content: "";
    display: block;
    width: 5px;
    height: 5px;
    margin: -2px 0 0 9px;
    border-radius: 50%;
    background: var(--arc);
  }
  .now-label {
    font-size: 12px;
    color: var(--arc);
  }

  .warn {
    color: var(--ember);
  }
  .reauth {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 10px;
    padding: 9px 12px;
    border: 1px solid rgba(255, 181, 71, 0.7);
    background: rgba(255, 181, 71, 0.07);
    color: var(--ember);
    font-size: 13.5px;
  }
  .btn {
    padding: 3px 10px;
    border: 1px solid var(--ember);
    color: var(--ember);
    font-size: 12.5px;
    text-decoration: none;
  }
  .empty {
    margin: 4px 0 0;
    color: var(--frost-3);
    font-size: 13.5px;
  }
  a {
    color: var(--arc);
  }
</style>
