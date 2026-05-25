"use client";

/* BackendHealthBanner — a slim top-of-page strip that surfaces when
 * the FastAPI backend at NEXT_PUBLIC_API_URL is unreachable. Polls
 * /health every 8 seconds; on failure shows a brick-red strip with
 * the diagnosis and a manual Retry button. Stays out of the way when
 * everything is fine (returns null).
 *
 * Mount inside both ChatWorkspaceMvp1 and ImageWorkspaceMvp2 (or any
 * surface that depends on the backend). Lightweight — one fetch per
 * interval, no heavy state. */

import { useCallback, useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
// /health sits at the bare origin, not under /api/v1 — strip the
// version suffix to find it.
const HEALTH_URL = API_BASE.replace(/\/api\/v\d+\/?$/, "") + "/health";

const POLL_MS = 8000;

type Status = "unknown" | "ok" | "offline";

export default function BackendHealthBanner() {
  const [status, setStatus] = useState<Status>("unknown");
  const [checking, setChecking] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);

  const ping = useCallback(async () => {
    setChecking(true);
    try {
      const ctrl = new AbortController();
      const timeout = setTimeout(() => ctrl.abort(), 4000);
      const res = await fetch(HEALTH_URL, { signal: ctrl.signal });
      clearTimeout(timeout);
      if (res.ok) {
        setStatus("ok");
        setLastError(null);
      } else {
        setStatus("offline");
        setLastError(`HTTP ${res.status}`);
      }
    } catch (e) {
      setStatus("offline");
      setLastError(
        e instanceof DOMException && e.name === "AbortError"
          ? "timeout (4s)"
          : e instanceof Error ? e.message : "unreachable",
      );
    } finally {
      setChecking(false);
    }
  }, []);

  // Initial ping on mount + simple polling. We previously gated on
  // document.visibilityState === "visible" as a politeness measure,
  // but headless / preview / iframe environments report "hidden"
  // even when active, which silently broke the banner during dev.
  // 8-second polling is cheap enough to leave unconditional.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (!cancelled) await ping();
    })();
    const id = setInterval(() => {
      if (!cancelled) void ping();
    }, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [ping]);

  if (status !== "offline") return null;

  return (
    <div className="relative z-50 bg-brick text-paper">
      <div className="px-5 py-2 flex items-center justify-between gap-3 text-[12.5px]">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono uppercase tracking-tagged text-[10.5px] shrink-0">
            Backend offline
          </span>
          <span className="text-paper/85 truncate">
            Can't reach <code className="font-mono">{HEALTH_URL}</code>
            {lastError ? ` — ${lastError}` : ""}
          </span>
        </div>
        <button
          type="button"
          onClick={() => void ping()}
          disabled={checking}
          className="shrink-0 px-2.5 py-1 rounded-md bg-paper/15 hover:bg-paper/25 transition-colors text-[11.5px] font-medium disabled:opacity-50"
        >
          {checking ? "Checking…" : "Retry"}
        </button>
      </div>
    </div>
  );
}
