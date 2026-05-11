/**
 * Toast store — global notification queue for transient errors,
 * warnings, and success confirmations that don't belong inline.
 *
 * Why a dedicated store
 * ---------------------
 * Inline error strings (``setGenerateError`` etc.) work fine for
 * persistent field-level feedback (the request *failed*, here's why,
 * retry when you want). They're a poor fit for ephemeral signals:
 *   • rate-limit "wait a second" warnings
 *   • network drops mid-stream
 *   • notes-save background failures
 *   • "saved" confirmations from message-toolbar actions
 *
 * Toasts cover those: they appear, sit for a few seconds, fade.
 *
 * Shape
 * -----
 * A toast is { id, type, title, message?, durationMs? }. The viewport
 * subscribes, auto-dismisses after ``durationMs`` (default 4500ms,
 * 0 = sticky), and offers explicit dismiss. Stack order is FIFO at
 * top-right of the viewport.
 *
 * Severity → register
 * -------------------
 * Severity drives colour ONLY, not layout. We map onto the chat
 * register:
 *   error    → pencil (the red architects mark drawings with)
 *   warning  → mustard
 *   success  → olive
 *   info     → indigo
 */

import { create } from "zustand";
import { ApiError } from "./api-client";

export type ToastType = "error" | "warning" | "success" | "info";

export interface Toast {
  id: string;
  type: ToastType;
  title: string;
  /** Optional supporting line. Keep short — one sentence. */
  message?: string;
  /** Milliseconds before auto-dismiss. 0 = sticky (user must dismiss). */
  durationMs?: number;
  /** Wall-clock when the toast was pushed (for sort + animation). */
  createdAt: number;
}

interface ToastState {
  toasts: Toast[];
  notify: (input: Omit<Toast, "id" | "createdAt"> & Partial<Pick<Toast, "id">>) => string;
  dismiss: (id: string) => void;
  clear: () => void;
}

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  notify: (input) => {
    const id = input.id ?? crypto.randomUUID();
    set((state) => {
      // De-dupe by id — a caller can reuse an id to *replace* an
      // existing toast (useful for streaming progress where the same
      // slot updates as state changes).
      const without = state.toasts.filter((t) => t.id !== id);
      return {
        toasts: [
          ...without,
          {
            id,
            type: input.type,
            title: input.title,
            message: input.message,
            durationMs: input.durationMs ?? 4500,
            createdAt: Date.now(),
          },
        ],
      };
    });
    return id;
  },
  dismiss: (id) =>
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
  clear: () => set({ toasts: [] }),
}));

/**
 * Unwrap an arbitrary error into a toast-friendly title/message pair.
 *
 * Backend envelope (Stage 0 ErrorResponse + Stage 13 envelope handler)
 * shape: ``{ error: string, message: string, details: [...] }``. The
 * top-level ``error`` is a stable code (e.g. ``rate_limit_exceeded``),
 * ``message`` is human prose. We prefer ``message`` for the toast body
 * and lift the code to a tag in the title so support can correlate.
 *
 * Falls back gracefully for plain ``Error`` and ``fetch`` rejection
 * (which is a TypeError in modern browsers).
 */
export function describeError(err: unknown, fallbackTitle: string): {
  title: string;
  message: string;
} {
  if (err instanceof ApiError) {
    const body = err.body as
      | { error?: string; message?: string; details?: Array<{ message: string }> }
      | null;
    // Rate-limit gets its own crisp label.
    if (err.status === 429) {
      return {
        title: "Rate limit hit",
        message: body?.message || "Too many requests — try again in a moment.",
      };
    }
    if (body?.message) {
      return {
        title: `${fallbackTitle} (${err.status})`,
        message: body.message,
      };
    }
    return {
      title: `${fallbackTitle} (${err.status})`,
      message: "The backend rejected the request.",
    };
  }
  // fetch() rejects with TypeError on network drop / CORS / DNS fail.
  if (err instanceof TypeError) {
    return {
      title: "Network",
      message: "Couldn't reach the backend. Check the connection and retry.",
    };
  }
  if (err instanceof Error) {
    return { title: fallbackTitle, message: err.message };
  }
  return { title: fallbackTitle, message: "Unknown error." };
}

/** Convenience — push a toast straight from a caught error. */
export function toastError(err: unknown, fallbackTitle: string): string {
  const { title, message } = describeError(err, fallbackTitle);
  return useToastStore.getState().notify({
    type: "error",
    title,
    message,
    durationMs: 6500,
  });
}
