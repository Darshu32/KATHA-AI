/**
 * useNotesPersist — wire ``useNotesStore`` to the server.
 *
 * Phase 1 sync layer. Mount once at the app shell level; thereafter
 * the hook quietly does three jobs:
 *
 * 1. **One-time migration push.** The first time a logged-in user
 *    runs the new sync layer, every section currently in
 *    localStorage is uploaded via ``POST /notes/import``. Server
 *    skips IDs it already has, so re-running is safe (idempotent).
 *
 * 2. **Hydrate-on-switch.** When the active conversation changes,
 *    GET its sections and merge them into the store. Hydrated
 *    conversations are remembered so we don't refetch on every
 *    panel toggle.
 *
 * 3. **Debounced flush.** Whenever ``dirtySectionIds`` or
 *    ``pendingDeletions`` change, schedule a flush 800ms later.
 *    Deletions go first (so a "create then delete" doesn't leak
 *    a row); upserts second.
 *
 * Known v1 race
 * -------------
 * If the user edits a section *during* its in-flight PUT, the edit
 * happens after we read ``getDirtySections()`` but before we mark
 * the section synced. The store keeps the new edit in memory but
 * clears the dirty flag, so the latest characters won't be pushed
 * until the next user action re-marks the section dirty. Acceptable
 * for v1 — the local copy stays correct, and a follow-up will add
 * version stamps for true conflict-free sync.
 */

"use client";

import { useEffect, useRef } from "react";

import api, { ApiError, type NoteSectionWire } from "./api-client";
import { useAuthStore, useChatStore, useNotesStore } from "./store";
import type { NoteSection } from "./types";

const SYNC_DEBOUNCE_MS = 800;

// Module-level flags so two simultaneous mounts (StrictMode in dev)
// don't double-fire the migration or flush calls.
let migrationInFlight = false;
let flushInFlight = false;

// ── Wire <-> store conversions ──────────────────────────────────────────

function wireToNoteSection(w: NoteSectionWire): NoteSection {
  return {
    id: w.id,
    title: w.title,
    date: w.client_created_at ?? w.created_at,
    sourceMessageId: w.source_message_id ?? "",
    sourceConversationId: w.conversation_id,
    blocks: (w.blocks as NoteSection["blocks"]) ?? [],
    tags: w.tags ?? [],
    imageUrl: w.image_url ?? null,
  };
}

function noteSectionToImportItem(s: NoteSection) {
  return {
    id: s.id,
    conversation_id: s.sourceConversationId,
    source_message_id: s.sourceMessageId || null,
    title: s.title,
    blocks: s.blocks,
    tags: s.tags ?? [],
    image_url: s.imageUrl ?? null,
    client_created_at: s.date || null,
  };
}

// ── Background workers ──────────────────────────────────────────────────

async function runMigrationIfNeeded(token: string): Promise<void> {
  const state = useNotesStore.getState();
  if (state.migratedToServer || migrationInFlight) return;
  migrationInFlight = true;
  try {
    const all = state.getAllSectionsFlat();
    if (all.length > 0) {
      await api.notes.import(all.map(noteSectionToImportItem), token);
    }
    // Mark migrated even when nothing was uploaded — the *check* is
    // done. We don't want to keep re-running this on every login of
    // a brand-new user.
    useNotesStore.getState().markMigrated();
    // Clear dirty for everything that was migrated. Anything edited
    // *after* migration will re-mark itself.
    for (const s of all) {
      useNotesStore.getState().markSectionSynced(s.id);
    }
  } catch (err) {
    // Non-fatal: leave migratedToServer=false so the next mount /
    // token change retries. Notes still work locally.
    // eslint-disable-next-line no-console
    console.warn("[notes] migration push failed; will retry", err);
  } finally {
    migrationInFlight = false;
  }
}

async function flush(token: string): Promise<void> {
  if (flushInFlight) return;
  flushInFlight = true;
  try {
    const state = useNotesStore.getState();
    if (!state.migratedToServer) return; // wait for migration first

    // ── Deletions first ──
    // Order matters: if a user creates then deletes the same section
    // before sync, we want the DELETE to find nothing (404, treated
    // as success) rather than a successful CREATE leaving an orphan
    // row.
    for (const sid of [...state.getPendingDeletions()]) {
      try {
        await api.notes.delete(sid, token);
        useNotesStore.getState().markDeletionSynced(sid);
      } catch (err) {
        // 404 means the row never existed server-side (or was
        // already deleted by another device). Either way, our
        // local pending-deletion is satisfied.
        if (err instanceof ApiError && err.status === 404) {
          useNotesStore.getState().markDeletionSynced(sid);
        }
        // Other errors: leave it pending; next debounce retries.
      }
    }

    // ── Then upserts ──
    // Re-read state so we pick up sections marked dirty *during* the
    // delete phase above.
    for (const sec of useNotesStore.getState().getDirtySections()) {
      try {
        await api.notes.upsert(
          sec.id,
          {
            conversation_id: sec.sourceConversationId,
            source_message_id: sec.sourceMessageId || null,
            title: sec.title,
            blocks: sec.blocks,
            tags: sec.tags ?? [],
            image_url: sec.imageUrl ?? null,
            client_created_at: sec.date || null,
          },
          token,
        );
        useNotesStore.getState().markSectionSynced(sec.id);
      } catch {
        // Leave dirty for next flush.
      }
    }
  } finally {
    flushInFlight = false;
  }
}

// ── The hook ─────────────────────────────────────────────────────────────

/**
 * Mount once at the app shell level. Triggers migration, hydration,
 * and debounced sync. No-op when no auth token is present.
 */
export function useNotesPersist(): void {
  const token = useAuthStore((s) => s.token);
  const activeConversationId = useChatStore((s) => s.activeConversationId);
  const migratedToServer = useNotesStore((s) => s.migratedToServer);

  // 1. One-time migration push.
  useEffect(() => {
    if (!token) return;
    void runMigrationIfNeeded(token);
  }, [token]);

  // 2. Hydrate the active conversation's notebook from the server,
  //    once per browser session per conversation, after migration.
  useEffect(() => {
    if (!token || !activeConversationId || !migratedToServer) return;
    const state = useNotesStore.getState();
    if (state.hydratedConversations.includes(activeConversationId)) return;

    api.notes
      .list(activeConversationId, token)
      .then(({ sections }) => {
        useNotesStore
          .getState()
          .hydrateConversation(
            activeConversationId,
            sections.map(wireToNoteSection),
          );
      })
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.warn("[notes] hydrate failed for", activeConversationId, err);
      });
  }, [token, activeConversationId, migratedToServer]);

  // 3. Debounced flush of dirty sections + pending deletions.
  //    We re-arm the timer only when the *set* of pending work
  //    changes (id added or removed) — content edits within an
  //    already-dirty section don't re-arm but are picked up by the
  //    flush at fire time, since flush reads current state.
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastKeyRef = useRef<string>("");

  useEffect(() => {
    if (!token) return;

    // Read once so we don't miss work that was already pending at
    // mount (e.g. dirty sections from before login).
    const initial = useNotesStore.getState();
    if (
      initial.dirtySectionIds.length > 0 ||
      initial.pendingDeletions.length > 0
    ) {
      timerRef.current = setTimeout(() => flush(token), SYNC_DEBOUNCE_MS);
    }

    const unsub = useNotesStore.subscribe((s) => {
      const key = `${s.dirtySectionIds.join(",")}|${s.pendingDeletions.join(",")}|${
        s.migratedToServer ? 1 : 0
      }`;
      if (key === lastKeyRef.current) return;
      lastKeyRef.current = key;

      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => flush(token), SYNC_DEBOUNCE_MS);
    });

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      unsub();
    };
  }, [token]);
}
