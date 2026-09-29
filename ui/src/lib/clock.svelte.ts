// One shared 1 Hz tick for every time-dependent label.
export const clock = $state({ now: Date.now() });

let timer: ReturnType<typeof setTimeout> | undefined;

function tick(): void {
  clock.now = Date.now();
  // Align to the next wall-clock second so the display never lags.
  timer = setTimeout(tick, 1000 - (clock.now % 1000) + 5);
}

export function startClock(): void {
  if (timer === undefined) tick();
}
