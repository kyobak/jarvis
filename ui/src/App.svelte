<script lang="ts">
  import { onMount } from "svelte";
  import AlertLayer from "./components/AlertLayer.svelte";
  import Backdrop from "./components/Backdrop.svelte";
  import Core from "./components/Core.svelte";
  import DevHelp from "./components/DevHelp.svelte";
  import FocusPanel from "./components/FocusPanel.svelte";
  import MessagesPanel from "./components/MessagesPanel.svelte";
  import NowPlayingPanel from "./components/NowPlayingPanel.svelte";
  import RemindersPanel from "./components/RemindersPanel.svelte";
  import SchedulePanel from "./components/SchedulePanel.svelte";
  import Subtitles from "./components/Subtitles.svelte";
  import TopBar from "./components/TopBar.svelte";
  import { startClock } from "./lib/clock.svelte";
  import { app, connect, dev, send } from "./lib/store.svelte";

  const BOOT_MS = 2800;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let booting = $state(!reduced);
  let helpOpen = $state(false);

  // Space: long-press (300 ms) to talk.
  let spaceTimer: ReturnType<typeof setTimeout> | undefined;
  let talking = false;

  const STATE_KEYS = ["idle", "listening", "thinking", "speaking", "alert", "offline"];

  function onKeyDown(e: KeyboardEvent): void {
    if (e.repeat) return;
    if (e.code === "Space") {
      e.preventDefault();
      spaceTimer = setTimeout(() => {
        talking = true;
        send("ptt", { down: true });
      }, 300);
      return;
    }
    if (e.key === "?") {
      helpOpen = !helpOpen;
      return;
    }
    if (!app.status?.dev) return;
    const n = Number(e.key);
    if (n >= 1 && n <= 6) return dev("state", STATE_KEYS[n - 1]);
    switch (e.key.toLowerCase()) {
      case "r": return dev("reminder");
      case "e": return dev("event");
      case "d": return dev("drowsy", e.shiftKey ? 2 : 1);
      case "m": return dev("message");
      case "g": return dev("gmail_expire");
      case "c": return dev("calendar_offline");
      case "f": return dev("focus");
      case "n": return dev("next_track");
      case "p": return dev("toggle_play");
      case "escape":
        helpOpen = false;
        return;
    }
  }

  function onKeyUp(e: KeyboardEvent): void {
    if (e.code !== "Space") return;
    clearTimeout(spaceTimer);
    if (talking) {
      talking = false;
      send("ptt", { down: false });
    }
  }

  onMount(() => {
    connect();
    startClock();
    if (booting) setTimeout(() => (booting = false), BOOT_MS);
  });
</script>

<svelte:window onkeydown={onKeyDown} onkeyup={onKeyUp} />

<Backdrop {booting} />

<main class="hud">
  <TopBar {booting} />

  <div class="columns">
    <div class="col left">
      <SchedulePanel {booting} delay={1500} />
      <RemindersPanel {booting} delay={1650} />
      <FocusPanel {booting} delay={1800} />
    </div>

    <div class="col center">
      <Core bootDelay={reduced ? 0 : 500} />
    </div>

    <div class="col right">
      <MessagesPanel {booting} delay={1575} />
      <NowPlayingPanel {booting} delay={1725} />
    </div>
  </div>

  <Subtitles />
</main>

<AlertLayer />
<DevHelp open={helpOpen} onclose={() => (helpOpen = false)} />

<style>
  .hud {
    position: relative;
    z-index: 1;
    display: grid;
    grid-template-rows: auto 1fr auto;
    height: 100%;
    padding: 26px 36px 22px;
    gap: 18px;
  }
  .columns {
    display: grid;
    grid-template-columns: minmax(300px, 350px) 1fr minmax(300px, 350px);
    gap: 28px;
    min-height: 0;
  }
  .col {
    display: flex;
    flex-direction: column;
    gap: 16px;
    min-height: 0;
  }
  .center {
    min-width: 0;
  }
</style>
