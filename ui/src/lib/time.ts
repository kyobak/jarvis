const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

export const pad = (n: number) => String(n).padStart(2, "0");

export function hhmm(d: Date): string {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function koreanDate(d: Date): string {
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${WEEKDAYS[d.getDay()]}요일`;
}

export function weekdayShort(iso: string): string {
  return WEEKDAYS[new Date(iso + "T00:00:00").getDay()];
}

/** "3시간 20분", "45분", "0분". */
export function duration(minutes: number): { h: number; m: number } {
  const total = Math.max(0, Math.round(minutes));
  return { h: Math.floor(total / 60), m: total % 60 };
}

/** "방금", "12분 전", "3시간 전", "어제". */
export function ago(iso: string, now: number): string {
  const min = Math.floor((now - Date.parse(iso)) / 60000);
  if (min < 1) return "방금";
  if (min < 60) return `${min}분 전`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}시간 전`;
  return h < 48 ? "어제" : `${Math.floor(h / 24)}일 전`;
}

/** Minutes until `iso`, rounded up. Negative when in the past. */
export function minutesUntil(iso: string, now: number): number {
  return Math.ceil((Date.parse(iso) - now) / 60000);
}

/** "m:ss" for track progress. */
export function mss(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${pad(s % 60)}`;
}

/** "mm:ss" countdown, hours folded into minutes. */
export function countdown(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000));
  return `${pad(Math.floor(s / 60))}:${pad(s % 60)}`;
}
