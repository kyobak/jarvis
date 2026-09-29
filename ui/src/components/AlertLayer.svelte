<script lang="ts">
  import { app, send } from "../lib/store.svelte";

  const alert = $derived(app.alert);
  const severe = $derived((alert?.level ?? 1) >= 2);

  const KIND_LABEL: Record<string, string> = {
    reminder: "리마인더",
    drowsy: "졸음 감지",
    event: "일정",
    info: "알림",
  };

  function ack(): void {
    send("alert_ack", { id: alert?.id });
  }

  function onKey(e: KeyboardEvent): void {
    if (alert && (e.key === "Escape" || e.key === "Enter")) ack();
  }
</script>

<svelte:window onkeydown={onKey} />

{#if alert}
  <div class="edge" class:severe aria-hidden="true"></div>
  <div class="card" class:severe role="alertdialog" aria-live="assertive">
    <span class="kind">{KIND_LABEL[alert.kind ?? "info"]}</span>
    <p class="title">{alert.title}</p>
    {#if alert.body}<p class="body">{alert.body}</p>{/if}
    <button onclick={ack}>확인</button>
  </div>
{/if}

<style>
  /* Pre-drawn gradient with an opacity-only pulse: cheap to composite. */
  .edge {
    position: fixed;
    inset: 0;
    pointer-events: none;
    background: radial-gradient(ellipse at center, transparent 55%, rgba(255, 181, 71, 0.22) 100%);
    animation: pulse 2.4s ease-in-out infinite;
    z-index: 5;
  }
  .edge.severe {
    background: radial-gradient(ellipse at center, transparent 45%, rgba(255, 77, 94, 0.32) 100%);
    animation-duration: 0.9s;
  }
  @keyframes pulse {
    0%, 100% { opacity: 0.45; }
    50% { opacity: 1; }
  }

  .card {
    --c: var(--ember);
    position: fixed;
    top: 110px;
    left: 50%;
    z-index: 6;
    min-width: 380px;
    max-width: 560px;
    padding: 18px 24px 16px;
    transform: translateX(-50%);
    background: rgba(12, 20, 28, 0.96);
    border: 1px solid var(--c);
    clip-path: polygon(0 0, calc(100% - 16px) 0, 100% 16px, 100% 100%, 0 100%);
    animation: drop 0.35s var(--ease-out);
  }
  .card.severe {
    --c: var(--flare);
  }
  @keyframes drop {
    from { opacity: 0; transform: translate(-50%, -8px); }
    to { opacity: 1; transform: translate(-50%, 0); }
  }
  .kind {
    font-size: 12px;
    color: var(--c);
  }
  .title {
    margin: 4px 0 0;
    font-size: 22px;
    font-weight: 600;
    color: var(--frost);
  }
  .body {
    margin: 4px 0 0;
    font-size: 14px;
    color: var(--frost-2);
  }
  button {
    margin-top: 14px;
    padding: 4px 16px;
    border: 1px solid var(--c);
    color: var(--c);
    font-size: 13px;
  }
  button:hover {
    background: rgba(255, 181, 71, 0.12);
  }
</style>
