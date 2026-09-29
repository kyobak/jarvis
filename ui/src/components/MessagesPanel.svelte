<script lang="ts">
  import { clock } from "../lib/clock.svelte";
  import { app } from "../lib/store.svelte";
  import { ago } from "../lib/time";
  import type { Mailbox, MessageItem } from "../lib/types";
  import Panel from "./Panel.svelte";

  let { booting = false, delay = 0 }: { booting?: boolean; delay?: number } = $props();

  type Source = "gmail" | "slack";
  const SOURCES: { key: Source; name: string; auth: string }[] = [
    { key: "gmail", name: "Gmail", auth: "/auth/google" },
    { key: "slack", name: "Slack", auth: "/auth/slack" },
  ];

  const boxes = $derived(app.messages);
  const merged = $derived.by(() => {
    if (!boxes) return [] as (MessageItem & { source: Source })[];
    return SOURCES.flatMap(({ key }) =>
      boxes[key].auth === "ok" || boxes[key].auth === "mock"
        ? boxes[key].items.map((m) => ({ ...m, source: key }))
        : [],
    )
      .sort((a, b) => Date.parse(b.received_at) - Date.parse(a.received_at))
      .slice(0, 4);
  });
  const needsReauth = $derived(SOURCES.filter(({ key }) => boxes?.[key].auth === "expired"));

  function linked(box: Mailbox | undefined): boolean {
    return !!box && (box.auth === "ok" || box.auth === "mock");
  }
</script>

<Panel title="메시지" {booting} {delay} grow>
  {#snippet meta()}
    <span class="counts">
      {#each SOURCES as s}
        <span class="count" class:off={!linked(boxes?.[s.key])}>
          {s.name}
          <span class="num">{linked(boxes?.[s.key]) ? boxes?.[s.key].count : "–"}</span>
        </span>
      {/each}
    </span>
  {/snippet}

  {#each needsReauth as s (s.key)}
    <div class="reauth">
      <span>{s.name} 다시 연결 필요</span>
      <a class="btn" href={s.auth} target="_blank">다시 연결</a>
    </div>
  {/each}

  {#if merged.length === 0 && needsReauth.length === 0}
    <p class="empty">
      {boxes && SOURCES.some(({ key }) => linked(boxes[key])) ? "새 메시지가 없어요." : "메일·슬랙이 연결되지 않았어요."}
    </p>
  {:else}
    <ul>
      {#each merged as m (m.id)}
        <li class:fresh={app.freshIds.includes(m.id)}>
          <span class="src {m.source}">{m.source === "gmail" ? "G" : "S"}</span>
          <div class="text">
            <div class="line1">
              <span class="sender ellipsis">{m.sender}</span>
              <span class="when">{ago(m.received_at, clock.now)}</span>
            </div>
            <div class="subject ellipsis">{m.subject}</div>
            <div class="snippet ellipsis">{m.snippet}</div>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</Panel>

<style>
  .counts {
    display: inline-flex;
    gap: 12px;
  }
  .count .num {
    margin-left: 3px;
    font-size: 14px;
    color: var(--arc);
  }
  .count.off,
  .count.off .num {
    color: var(--tide);
  }

  ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    position: relative;
    display: grid;
    grid-template-columns: 22px 1fr;
    gap: 10px;
    padding: 8px 0;
    border-bottom: 1px solid rgba(30, 90, 115, 0.22);
  }
  li:last-child {
    border-bottom: 0;
  }
  li.fresh::before {
    content: "";
    position: absolute;
    left: -18px;
    top: 8px;
    bottom: 8px;
    width: 2px;
    background: var(--arc);
    animation: fresh 6s ease-out forwards;
  }
  @keyframes fresh {
    0%, 60% { opacity: 1; }
    100% { opacity: 0; }
  }

  .src {
    display: grid;
    place-items: center;
    width: 20px;
    height: 20px;
    margin-top: 2px;
    border: 1px solid var(--tide-line);
    font-family: var(--font-num);
    font-size: 11px;
    color: var(--frost-2);
  }
  .text {
    min-width: 0;
  }
  .line1 {
    display: flex;
    justify-content: space-between;
    gap: 8px;
  }
  .sender {
    font-size: 14px;
    font-weight: 600;
  }
  .when {
    flex: none;
    font-size: 12px;
    color: var(--frost-3);
  }
  .subject {
    font-size: 13.5px;
    color: var(--frost-2);
  }
  .snippet {
    font-size: 12.5px;
    color: var(--frost-3);
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
  .btn:hover {
    background: rgba(255, 181, 71, 0.15);
  }
  .empty {
    margin: 0;
    color: var(--frost-3);
    font-size: 13.5px;
  }
</style>
