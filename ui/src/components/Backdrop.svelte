<script lang="ts">
  // Static grid plus a one-time boot sequence: guide lines draw in, then the grid fades up.
  let { booting = false }: { booting?: boolean } = $props();

  const H_LINES = [0.12, 0.5, 0.88];
  const V_LINES = [0.27, 0.5, 0.73];
</script>

<div class="backdrop" class:booting aria-hidden="true">
  <div class="grid"></div>
  <div class="halo"></div>
  <div class="guides">
    {#each H_LINES as y, i}
      <span class="h" style:top="{y * 100}%" style:--i={i}></span>
    {/each}
    {#each V_LINES as x, i}
      <span class="v" style:left="{x * 100}%" style:--i={i + 3}></span>
    {/each}
  </div>
</div>

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 0;
  }
  .grid {
    position: absolute;
    inset: 0;
    background-image:
      linear-gradient(rgba(30, 90, 115, 0.13) 1px, transparent 1px),
      linear-gradient(90deg, rgba(30, 90, 115, 0.13) 1px, transparent 1px);
    background-size: 48px 48px;
    background-position: center center;
    -webkit-mask-image: radial-gradient(ellipse at center, #000 30%, transparent 78%);
    mask-image: radial-gradient(ellipse at center, #000 30%, transparent 78%);
  }
  .halo {
    position: absolute;
    inset: 0;
    background: radial-gradient(circle at 50% 50%, rgba(92, 225, 255, 0.06), transparent 45%);
  }
  .guides {
    position: absolute;
    inset: 0;
    opacity: 0;
  }
  .guides span {
    position: absolute;
    background: rgba(92, 225, 255, 0.35);
  }
  .guides .h {
    left: 0;
    right: 0;
    height: 1px;
    transform: scaleX(0);
  }
  .guides .v {
    top: 0;
    bottom: 0;
    width: 1px;
    transform: scaleY(0);
  }

  .booting .grid,
  .booting .halo {
    opacity: 0;
    animation: fade-in 0.9s ease-out 0.9s forwards;
  }
  .booting .guides {
    animation: guides 2.6s ease-in-out forwards;
  }
  .booting .guides span {
    animation: draw 0.9s var(--ease-out) forwards;
    animation-delay: calc(var(--i) * 70ms);
  }
  @keyframes draw {
    to {
      transform: none;
    }
  }
  @keyframes guides {
    0% { opacity: 1; }
    55% { opacity: 1; }
    100% { opacity: 0; }
  }
  @keyframes fade-in {
    to {
      opacity: 1;
    }
  }
</style>
