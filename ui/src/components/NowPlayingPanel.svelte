<script lang="ts">
  import { clock } from "../lib/clock.svelte";
  import { app } from "../lib/store.svelte";
  import { mss } from "../lib/time";
  import Panel from "./Panel.svelte";

  let { booting = false, delay = 0 }: { booting?: boolean; delay?: number } = $props();

  const np = $derived(app.nowPlaying);
  const linked = $derived(app.status?.integrations.spotify !== "disabled");

  // Interpolate progress locally between server updates.
  const progress = $derived.by(() => {
    if (!np?.title || !np.duration_ms) return 0;
    const elapsed = np.is_playing ? clock.now - (np.updated_at ?? clock.now) : 0;
    return Math.min(np.duration_ms, (np.progress_ms ?? 0) + elapsed);
  });
  const ratio = $derived(np?.duration_ms ? progress / np.duration_ms : 0);
  const hue = $derived(np?.art_hue ?? 196);
</script>

<Panel title="재생 중" {booting} {delay}>
  {#snippet meta()}Spotify{/snippet}

  {#if np?.title}
    <div class="track">
      <div class="art" style:--h={hue}>
        {#if np.art_url}
          <img src={np.art_url} alt="" />
        {:else}
          <span class="rings"></span>
        {/if}
      </div>
      <div class="info">
        <div class="title ellipsis">{np.title}</div>
        <div class="artist ellipsis">{np.artist}</div>
        <div class="album ellipsis">{np.album}</div>
      </div>
      <span class="play-state" class:paused={!np.is_playing}>{np.is_playing ? "재생" : "일시정지"}</span>
    </div>
    <div class="progress">
      <span class="bar"><span class="fill" style:transform="scaleX({ratio})"></span></span>
      <span class="num t">{mss(progress)} <span class="dur">/ {mss(np.duration_ms ?? 0)}</span></span>
    </div>
  {:else}
    <p class="empty">{linked ? "재생 중인 음악이 없어요." : "Spotify가 연결되지 않았어요."}</p>
  {/if}
</Panel>

<style>
  .track {
    display: grid;
    grid-template-columns: 64px 1fr auto;
    gap: 14px;
    align-items: center;
  }
  .art {
    position: relative;
    width: 64px;
    height: 64px;
    overflow: hidden;
    background:
      radial-gradient(circle at 30% 25%, hsla(var(--h), 90%, 70%, 0.9), transparent 60%),
      linear-gradient(135deg, hsl(var(--h), 55%, 28%), hsl(calc(var(--h) + 40), 60%, 12%));
    clip-path: polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 0 100%);
  }
  .art img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .rings {
    position: absolute;
    inset: 12px;
    border-radius: 50%;
    border: 1px solid rgba(255, 255, 255, 0.35);
    box-shadow: inset 0 0 0 8px rgba(0, 0, 0, 0.12), inset 0 0 0 9px rgba(255, 255, 255, 0.2);
  }
  .info {
    min-width: 0;
  }
  .title {
    font-size: 15.5px;
    font-weight: 600;
  }
  .artist {
    font-size: 13.5px;
    color: var(--frost-2);
  }
  .album {
    font-size: 12px;
    color: var(--frost-3);
  }
  .play-state {
    align-self: start;
    font-size: 11.5px;
    color: var(--arc);
  }
  .play-state.paused {
    color: var(--frost-3);
  }
  .progress {
    display: grid;
    grid-template-columns: 1fr auto;
    align-items: center;
    gap: 12px;
    margin-top: 14px;
  }
  .bar {
    position: relative;
    height: 2px;
    background: var(--tide-faint);
  }
  .fill {
    position: absolute;
    inset: 0;
    background: var(--arc);
    transform-origin: 0 50%;
    transition: transform 1s linear;
  }
  .t {
    font-size: 13px;
    color: var(--frost);
  }
  .dur {
    color: var(--frost-3);
  }
  .empty {
    margin: 0;
    color: var(--frost-3);
    font-size: 13.5px;
  }
</style>
