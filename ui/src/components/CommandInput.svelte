<script lang="ts">
  import { tick } from "svelte";
  import { app, send } from "../lib/store.svelte";

  let value = $state("");
  let input: HTMLInputElement | undefined = $state();

  $effect(() => {
    if (app.commandOpen) tick().then(() => input?.focus());
  });

  function close(): void {
    app.commandOpen = false;
    value = "";
  }

  function onKey(e: KeyboardEvent): void {
    e.stopPropagation();
    if (e.key === "Escape") close();
    if (e.key === "Enter" && !e.isComposing && value.trim()) {
      send("text", { text: value.trim() });
      close();
    }
  }
</script>

{#if app.commandOpen}
  <div class="command">
    <span class="prompt num">&gt;</span>
    <input
      bind:this={input}
      bind:value
      onkeydown={onKey}
      onblur={close}
      placeholder="자비스에게 입력하기 — Enter로 보내기, Esc로 닫기"
      maxlength="300"
      autocomplete="off"
      spellcheck="false"
    />
  </div>
{/if}

<style>
  .command {
    position: fixed;
    left: 50%;
    bottom: 90px;
    z-index: 7;
    display: flex;
    align-items: center;
    gap: 10px;
    width: min(620px, 80vw);
    padding: 10px 16px;
    transform: translateX(-50%);
    background: rgba(7, 19, 30, 0.97);
    border: 1px solid var(--arc-dim);
    clip-path: polygon(0 0, calc(100% - 12px) 0, 100% 12px, 100% 100%, 0 100%);
  }
  .prompt {
    color: var(--arc);
  }
  input {
    flex: 1;
    border: 0;
    outline: 0;
    background: transparent;
    color: var(--frost);
    font: inherit;
    font-size: 16px;
    user-select: text;
  }
  input::placeholder {
    color: var(--frost-3);
  }
</style>
