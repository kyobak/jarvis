<script lang="ts">
  import { clock } from "../lib/clock.svelte";
  import { app } from "../lib/store.svelte";

  const HOLD_MS = 9000;
  const active = $derived(
    app.core === "listening" || app.core === "thinking" || app.core === "speaking" || clock.now - app.transcriptAt < HOLD_MS,
  );
</script>

<div class="subs" class:hidden={!active || (!app.userLine && !app.jarvisLine)}>
  {#if app.userLine}
    <p class="user" class:partial={!app.userLine.final}>“{app.userLine.text}”</p>
  {/if}
  {#if app.jarvisLine}
    <p class="jarvis">{app.jarvisLine.text}</p>
  {/if}
</div>

<style>
  .subs {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-end;
    gap: 6px;
    min-height: 72px;
    text-align: center;
    transition: opacity 0.6s;
  }
  .hidden {
    opacity: 0;
  }
  p {
    margin: 0;
    max-width: 820px;
  }
  .user {
    font-size: 17px;
    color: var(--frost-2);
  }
  .user.partial {
    color: var(--frost-3);
  }
  .jarvis {
    font-size: 21px;
    font-weight: 500;
    color: var(--frost);
  }
</style>
