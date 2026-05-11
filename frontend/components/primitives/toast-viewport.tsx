"use client";

/**
 * ToastViewport — bottom-right stack of transient notifications.
 *
 * Position: bottom-right rather than the more common top-right so it
 * doesn't fight the right-rail Sources gutter on chat. Bottom-right
 * keeps the eye in the prose region while still being noticed.
 *
 * Severity → colour
 * -----------------
 * Type is mapped onto the chat register tokens — pencil for errors
 * (the red architects mark drawings with), mustard for warnings,
 * olive for success, indigo for info. All toasts share the same
 * white-paper surface; only the left rail accent and icon hue change.
 *
 * Animation
 * ---------
 * Framer-motion slide-up + fade. ``prefers-reduced-motion`` collapses
 * to a simple opacity transition. Auto-dismiss is a per-toast
 * ``setTimeout`` cleared on unmount.
 */

import { useEffect } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import {
  AlertTriangle,
  AlertCircle,
  CheckCircle2,
  Info,
  X,
} from "lucide-react";
import { useToastStore, type Toast, type ToastType } from "@/lib/toast-store";

const STYLES: Record<
  ToastType,
  { rail: string; iconColor: string; Icon: typeof Info }
> = {
  error: { rail: "bg-pencil", iconColor: "text-pencil", Icon: AlertCircle },
  warning: { rail: "bg-mustard", iconColor: "text-mustard", Icon: AlertTriangle },
  success: { rail: "bg-olive", iconColor: "text-olive", Icon: CheckCircle2 },
  info: { rail: "bg-indigo", iconColor: "text-indigo", Icon: Info },
};

export default function ToastViewport() {
  const toasts = useToastStore((s) => s.toasts);
  return (
    <div
      // ``aria-live=polite`` so screen readers announce new toasts
      // without interrupting whatever the user is doing. ``role=region``
      // gives them a navigable landmark.
      aria-live="polite"
      role="region"
      aria-label="Notifications"
      className="fixed bottom-5 right-5 z-[60] flex flex-col gap-2 w-[min(360px,90vw)] pointer-events-none"
    >
      <AnimatePresence initial={false}>
        {toasts.map((t) => (
          <ToastRow key={t.id} toast={t} />
        ))}
      </AnimatePresence>
    </div>
  );
}

function ToastRow({ toast }: { toast: Toast }) {
  const dismiss = useToastStore((s) => s.dismiss);
  const reduced = useReducedMotion();
  const style = STYLES[toast.type];
  const Icon = style.Icon;

  useEffect(() => {
    if (!toast.durationMs || toast.durationMs <= 0) return;
    const t = setTimeout(() => dismiss(toast.id), toast.durationMs);
    return () => clearTimeout(t);
  }, [toast.id, toast.durationMs, dismiss]);

  return (
    <motion.div
      // Reduced-motion users get a plain fade. Everyone else gets a
      // small slide-in from the right edge — quick, no bounce.
      initial={reduced ? { opacity: 0 } : { opacity: 0, x: 20, y: 4 }}
      animate={reduced ? { opacity: 1 } : { opacity: 1, x: 0, y: 0 }}
      exit={reduced ? { opacity: 0 } : { opacity: 0, x: 20, y: 4 }}
      transition={{ duration: reduced ? 0.12 : 0.18, ease: "easeOut" }}
      className="pointer-events-auto relative flex items-start gap-3 bg-paper border border-hairline shadow-card rounded-lg overflow-hidden"
      role={toast.type === "error" ? "alert" : "status"}
    >
      {/* Coloured left rail — the only chrome that varies by severity. */}
      <span className={`absolute inset-y-0 left-0 w-[3px] ${style.rail}`} />
      <div className="flex items-start gap-2.5 pl-4 pr-3 py-2.5 flex-1 min-w-0">
        <Icon size={14} className={`${style.iconColor} mt-[2px] shrink-0`} />
        <div className="flex-1 min-w-0">
          <p className="text-[13px] text-ink-deep font-medium tracking-tight leading-tight">
            {toast.title}
          </p>
          {toast.message ? (
            <p className="mt-0.5 text-[12px] text-ink-soft leading-snug">
              {toast.message}
            </p>
          ) : null}
        </div>
        <button
          onClick={() => dismiss(toast.id)}
          className="text-ink-mute hover:text-ink-deep hover:bg-paper-soft rounded p-0.5 transition-colors shrink-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-ink-deep/40"
          aria-label="Dismiss notification"
        >
          <X size={12} />
        </button>
      </div>
    </motion.div>
  );
}
