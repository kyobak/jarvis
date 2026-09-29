import type {
  Alert,
  CoreState,
  Drowsiness,
  Focus,
  Messages,
  NowPlaying,
  Reminder,
  Schedule,
  ServerEvent,
  Status,
  Transcript,
} from "./types";

export const app = $state({
  connected: false,
  everConnected: false,
  core: "idle" as CoreState,
  status: null as Status | null,
  schedule: null as Schedule | null,
  reminders: [] as Reminder[],
  messages: null as Messages | null,
  nowPlaying: null as NowPlaying | null,
  focus: null as Focus | null,
  drowsiness: null as Drowsiness | null,
  alert: null as Alert | null,
  userLine: null as Transcript | null,
  jarvisLine: null as Transcript | null,
  transcriptAt: 0,
  /** Message ids that arrived after the first snapshot; used for a one-shot highlight. */
  freshIds: [] as string[],
});

/** The core's visible state: a lost server connection overrides everything. */
export function visibleCore(): CoreState {
  return app.connected || !app.everConnected ? app.core : "offline";
}

// Audio level is read every animation frame, so it lives outside reactive state.
export const audio = { level: 0 };

let socket: WebSocket | null = null;
let retry = 0;
let seenMessageIds: Set<string> | null = null;

function apply(event: ServerEvent): void {
  switch (event.type) {
    case "status":
      app.status = event.payload;
      break;
    case "state":
      app.core = event.payload.core;
      break;
    case "schedule":
      app.schedule = event.payload;
      break;
    case "reminders":
      app.reminders = event.payload.items;
      break;
    case "messages": {
      const ids = [...event.payload.gmail.items, ...event.payload.slack.items].map((m) => m.id);
      if (seenMessageIds) app.freshIds = ids.filter((id) => !seenMessageIds!.has(id));
      seenMessageIds = new Set(ids);
      app.messages = event.payload;
      break;
    }
    case "now_playing":
      app.nowPlaying = event.payload;
      break;
    case "focus":
      app.focus = event.payload;
      break;
    case "drowsiness":
      app.drowsiness = event.payload;
      break;
    case "alert":
      app.alert = event.payload.active ? event.payload : null;
      break;
    case "transcript":
      if (event.payload.role === "user") {
        app.userLine = event.payload;
        if (event.payload.final === false && app.jarvisLine) app.jarvisLine = null;
      } else {
        app.jarvisLine = event.payload;
      }
      app.transcriptAt = Date.now();
      break;
    case "level":
      audio.level = event.payload.v;
      break;
  }
}

export function connect(): void {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${proto}://${location.host}/ws`);
  socket.onopen = () => {
    retry = 0;
    app.connected = true;
    app.everConnected = true;
  };
  socket.onmessage = (msg) => {
    try {
      apply(JSON.parse(msg.data) as ServerEvent);
    } catch (err) {
      console.error("bad event", err);
    }
  };
  socket.onclose = () => {
    app.connected = false;
    audio.level = 0;
    socket = null;
    const delay = Math.min(5000, 500 * 2 ** retry++);
    setTimeout(connect, delay);
  };
}

export function send(type: string, payload: Record<string, unknown> = {}): void {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type, payload }));
}

export function dev(action: string, value?: unknown): void {
  if (app.status?.dev) send("dev", { action, value });
}
