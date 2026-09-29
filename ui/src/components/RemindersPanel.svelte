<script lang="ts">
  import { clock } from "../lib/clock.svelte";
  import { app, send } from "../lib/store.svelte";
  import { hhmm } from "../lib/time";
  import Panel from "./Panel.svelte";

  let { booting = false, delay = 0 }: { booting?: boolean; delay?: number } = $props();

  const items = $derived(app.reminders.slice(0, 4));

  function dayLabel(iso: string): string {
    const d = new Date(iso);
    const today = new Date(clock.now);
    const diff = Math.round(
      (new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() -
        new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()) /
        86400000,
    );
    return diff === 0 ? "" : diff === 1 ? "내일" : `${d.getMonth() + 1}/${d.getDate()}`;
  }
</script>

<Panel title="리마인더" {booting} {delay}>
  {#snippet meta()}<span class="num">{app.reminders.length}</span>개{/snippet}

  {#if items.length === 0}
    <p class="empty">등록된 리마인더가 없어요.<br /><span>“4시 반에 알려줘”처럼 말해 보세요.</span></p>
  {:else}
    <ul>
      {#each items as r (r.id)}
        <li>
          <span class="time num">{hhmm(new Date(r.when))}</span>
          <span class="msg ellipsis">{r.message}</span>
          {#if r.repeat}
            <span class="tag">{r.repeat}</span>
          {:else if dayLabel(r.when)}
            <span class="tag muted">{dayLabel(r.when)}</span>
          {:else}
            <span></span>
          {/if}
          <button class="x" aria-label="{r.message} 취소" onclick={() => send("reminder_cancel", { id: r.id })}>×</button>
        </li>
      {/each}
    </ul>
  {/if}
</Panel>

<style>
  ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    display: grid;
    grid-template-columns: 52px 1fr auto 18px;
    align-items: center;
    gap: 6px;
    min-height: 30px;
  }
  .time {
    font-size: 15px;
    color: var(--arc);
  }
  .msg {
    font-size: 14.5px;
  }
  .tag {
    padding: 1px 7px;
    border: 1px solid var(--tide-line);
    font-size: 11.5px;
    color: var(--frost-2);
  }
  .tag.muted {
    border-color: transparent;
    color: var(--frost-3);
  }
  .x {
    color: var(--tide);
    font-size: 15px;
    line-height: 1;
    opacity: 0;
    transition: opacity 0.2s, color 0.2s;
  }
  li:hover .x {
    opacity: 1;
  }
  .x:hover {
    color: var(--ember);
  }
  .empty {
    margin: 0;
    font-size: 13.5px;
    color: var(--frost-2);
  }
  .empty span {
    color: var(--frost-3);
  }
</style>
