// Wire types for server → UI events. See CLAUDE.md "WebSocket protocol".

export type CoreState = "idle" | "listening" | "thinking" | "speaking" | "alert" | "offline";
export type LinkState = "ok" | "mock" | "offline" | "expired" | "disabled" | "error";

export interface Status {
  mock: boolean;
  dev: boolean;
  user_name: string;
  camera: "on" | "off" | "paused" | "mock";
  mic: "on" | "off" | "mock";
  integrations: Record<"calendar" | "gmail" | "slack" | "spotify" | "ai", LinkState>;
  llm: {
    calls: number;
    tokens: number;
    limit: number;
    backend?: "openai_compat" | "api" | "claude_code" | "off" | "mock";
    /** Display name of the AI in use, e.g. "Gemini", "Claude". */
    label?: string;
  };
  wake_word?: boolean;
}

export interface CalendarEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  calendar: string;
  all_day?: boolean;
}

export interface Schedule {
  events: CalendarEvent[];
  synced_at: string | null;
  offline: boolean;
}

export interface Reminder {
  id: number;
  message: string;
  when: string;
  repeat: string | null;
}

export interface MessageItem {
  id: string;
  sender: string;
  subject: string;
  snippet: string;
  received_at: string;
}

export interface Mailbox {
  auth: LinkState;
  count: number;
  items: MessageItem[];
}

export interface Messages {
  gmail: Mailbox;
  slack: Mailbox;
}

export interface NowPlaying {
  title: string | null;
  artist?: string;
  album?: string;
  art_url?: string | null;
  art_hue?: number;
  duration_ms?: number;
  progress_ms?: number;
  updated_at?: number;
  is_playing?: boolean;
  volume?: number;
}

export interface FocusSession {
  planned_min: number;
  started_at: number;
  ends_at: number;
  paused: boolean;
}

export interface Focus {
  today_min: number;
  week: { date: string; min: number }[];
  session: FocusSession | null;
}

export interface Alert {
  id: number;
  kind?: "reminder" | "drowsy" | "event" | "info";
  level?: 1 | 2;
  title?: string;
  body?: string;
  active: boolean;
}

export interface Transcript {
  role: "user" | "jarvis";
  text: string;
  final: boolean;
  /** jarvis only: who produced the reply (local | llm | limit | error). */
  source?: string;
}

export interface Drowsiness {
  score: number;
  enabled: boolean;
  nap_until: string | null;
}

export type ServerEvent =
  | { type: "status"; payload: Status }
  | { type: "state"; payload: { core: CoreState } }
  | { type: "schedule"; payload: Schedule }
  | { type: "reminders"; payload: { items: Reminder[] } }
  | { type: "messages"; payload: Messages }
  | { type: "now_playing"; payload: NowPlaying }
  | { type: "focus"; payload: Focus }
  | { type: "alert"; payload: Alert }
  | { type: "transcript"; payload: Transcript }
  | { type: "drowsiness"; payload: Drowsiness }
  | { type: "level"; payload: { v: number } };
