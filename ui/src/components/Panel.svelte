<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    title,
    meta,
    tone = "normal",
    delay = 0,
    booting = false,
    grow = false,
    children,
  }: {
    title: string;
    meta?: Snippet;
    tone?: "normal" | "warn" | "muted";
    delay?: number;
    booting?: boolean;
    grow?: boolean;
    children: Snippet;
  } = $props();
</script>

<section class="panel {tone}" class:booting class:grow style:--delay="{delay}ms">
  <header>
    <h2>{title}</h2>
    <span class="rule"></span>
    {#if meta}<span class="meta">{@render meta()}</span>{/if}
  </header>
  <div class="body">{@render children()}</div>
  <span class="bracket" aria-hidden="true"></span>
</section>

<style>
  .panel {
    position: relative;
    display: flex;
    flex-direction: column;
    min-height: 0;
    padding: 14px 18px 16px;
    background: var(--hull);
    border: 1px solid var(--tide-line);
    clip-path: polygon(0 0, calc(100% - var(--cut)) 0, 100% var(--cut), 100% 100%, 0 100%);
  }
  .panel.grow {
    flex: 1;
  }
  /* The one angled corner: a 1px diagonal matching the border. */
  .panel::after {
    content: "";
    position: absolute;
    /* Starts where the clip polygon cuts the top edge (border-box coords). */
    top: -1px;
    left: calc(100% - var(--cut) + 1px);
    width: calc(var(--cut) * 1.4142);
    height: 1px;
    background: var(--tide-line);
    transform-origin: 0 0;
    transform: rotate(45deg);
  }
  .panel.warn {
    border-color: rgba(255, 181, 71, 0.75);
  }
  .panel.warn::after {
    background: rgba(255, 181, 71, 0.75);
  }

  .bracket {
    position: absolute;
    left: -1px;
    bottom: -1px;
    width: 10px;
    height: 10px;
    border-left: 1px solid var(--arc-dim);
    border-bottom: 1px solid var(--arc-dim);
  }

  header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
  }
  h2 {
    margin: 0;
    font-size: 13px;
    font-weight: 600;
    color: var(--frost-2);
    white-space: nowrap;
  }
  h2::before {
    content: "";
    display: inline-block;
    width: 6px;
    height: 1px;
    margin-right: 8px;
    vertical-align: middle;
    background: var(--arc);
  }
  .rule {
    flex: 1;
    height: 1px;
    background: var(--tide-faint);
  }
  .meta {
    font-size: 12px;
    color: var(--frost-3);
    white-space: nowrap;
  }
  .body {
    min-height: 0;
    flex: 1;
  }

  .booting {
    opacity: 0;
    animation: panel-in 0.55s var(--ease-out) forwards;
    animation-delay: var(--delay);
  }
  @keyframes panel-in {
    from {
      opacity: 0;
      transform: translateY(6px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }
</style>
