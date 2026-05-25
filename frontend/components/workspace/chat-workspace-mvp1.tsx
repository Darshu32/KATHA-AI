"use client";

/* MVP 1 — Chat workspace.
 * Editorial Claude-inspired layout: quiet left sidebar of conversations,
 * centered conversation column with serif headlines + sans body, optional
 * right notes pane that auto-opens in Deep mode. Minimal chrome. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Copy, Link2, BookmarkPlus, Pencil, Check } from "lucide-react";
import { useChatStore, useNotesStore } from "@/lib/store";
import { chat as chatApi } from "@/lib/api-client";
import { parseDeepModeToNotes } from "@/lib/notes-parser";
import { useNotesPersist } from "@/lib/use-notes-persist";
import { processChildren } from "@/lib/chat-callouts";
import { toastError, useToastStore } from "@/lib/toast-store";
import type { ChatMode, Message } from "@/lib/types";
import { SectionTag } from "@/components/primitives";
import BackendHealthBanner from "@/components/primitives/backend-health-banner";
import NotesSidebar from "@/components/notes/notes-sidebar";

// Unicode circled numerals for ref markers. Goes up to ①–⑳. Beyond
// that we fall back to "(N)" — architects rarely cite more than 5
// sources in a single answer, so the cap is theoretical.
const REF_MARKERS = [
  "①", "②", "③", "④", "⑤",
  "⑥", "⑦", "⑧", "⑨", "⑩",
  "⑪", "⑫", "⑬", "⑭", "⑮",
  "⑯", "⑰", "⑱", "⑲", "⑳",
];
const refMarker = (i: number) =>
  i < REF_MARKERS.length ? REF_MARKERS[i] : `(${i + 1})`;

/* Normalise a paragraph's text into a key suitable for map lookup.
   Whitespace runs collapse, leading/trailing trim, lowercase — so
   trivial formatting drift between the raw message string and the
   rendered React children doesn't break the lookup. */
function normaliseParagraphKey(s: string): string {
  return s.replace(/\s+/g, " ").trim().toLowerCase();
}

/* Walk React children and return their concatenated plain text. Used
   to derive a stable lookup key for the paragraph-renderer hook. */
function extractPlainText(node: React.ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractPlainText).join("");
  if (typeof node === "object" && "props" in node) {
    const el = node as React.ReactElement<{ children?: React.ReactNode }>;
    return extractPlainText(el.props.children);
  }
  return "";
}

const MODES: { id: ChatMode; label: string; tagline: string }[] = [
  { id: "quick", label: "Quick", tagline: "short, focused answers" },
  { id: "deep", label: "Deep", tagline: "long-form with notes" },
  { id: "auto", label: "Auto", tagline: "adapts to the question" },
];

export default function ChatWorkspaceMvp1() {
  const {
    conversations,
    activeConversationId,
    isStreaming,
    chatMode,
    sidebarOpen,
    createConversation,
    setActiveConversation,
    addMessage,
    appendToLastMessage,
    updateLastMessageFull,
    setStreaming,
    setChatMode,
    toggleSidebar,
    deleteConversation,
    mergeBrief,
  } = useChatStore();

  const notesPanelOpen = useNotesStore((s) => s.notesPanelOpen);
  const setNotesPanelOpen = useNotesStore((s) => s.setNotesPanelOpen);

  // Phase 1 sync: pushes localStorage notes to server on first run,
  // hydrates each conversation's notebook on switch, and debounce-
  // syncs every edit. No-op when not logged in.
  useNotesPersist();

  const abortRef = useRef<AbortController | null>(null);
  const [input, setInput] = useState("");
  const transcriptRef = useRef<HTMLDivElement | null>(null);

  const activeConversation = useMemo(
    () => conversations.find((c) => c.id === activeConversationId) ?? null,
    [conversations, activeConversationId],
  );

  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
    }
  }, [activeConversation?.messages.length, isStreaming]);

  useEffect(() => {
    if (chatMode === "deep") setNotesPanelOpen(true);
  }, [chatMode, setNotesPanelOpen]);

  // First-mount mobile guard — collapse the conversation sidebar on
  // small viewports so the chat reads as a full-width column. Above
  // md the sidebar's default state is preserved. The 200ms delay
  // gives the zustand-persist rehydration time to settle before we
  // override; otherwise our setSidebarOpen(false) can be clobbered
  // by the rehydrated value. Runs once per mount.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const id = setTimeout(() => {
      if (window.matchMedia("(max-width: 767px)").matches) {
        useChatStore.getState().setSidebarOpen(false);
      }
    }, 200);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isStreaming) return;

      let convoId = activeConversationId;
      if (!convoId) convoId = createConversation();

      const now = new Date().toISOString();
      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: "user",
        content: trimmed,
        timestamp: now,
        mode: chatMode,
      };
      addMessage(convoId, userMsg);

      const placeholder: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
        isStreaming: true,
        mode: chatMode,
      };
      addMessage(convoId, placeholder);

      setInput("");
      setStreaming(true);

      const history = (activeConversation?.messages ?? []).map((m) => ({
        role: m.role,
        content: m.content,
      }));

      abortRef.current = new AbortController();

      try {
        await chatApi.stream(
          trimmed,
          history,
          chatMode,
          {
            onToken: (tok) => appendToLastMessage(convoId!, tok),
            onDone: async (data) => {
              updateLastMessageFull(convoId!, {
                content: data.content,
                isStreaming: false,
                suggestions: data.suggestions,
                referenceLinks: data.reference_links?.map((r) => ({
                  title: r.title,
                  url: r.url,
                  type:
                    (r.type as
                      | "article"
                      | "standard"
                      | "documentation"
                      | "other") ?? "other",
                })),
              });
              // BRD §1A — fold any brief snapshot from this Deep
              // response into the conversation. The store no-ops when
              // ``brief`` is null (i.e. the user was asking a knowledge
              // question, not briefing a project), so this is safe to
              // call unconditionally.
              if (convoId && data.mode === "deep") {
                mergeBrief(convoId, {
                  brief: data.brief,
                  status: data.brief_status,
                  missing: data.brief_missing,
                });
              }
              // Deep Mode answers become auto-saved notes, scoped to
              // the originating conversation. The persist hook syncs
              // the new section to the server.
              //
              // The check on ``data.mode`` rather than ``chatMode`` is
              // deliberate: when chatMode is "auto", the backend is the
              // one that decides quick vs. deep, and reports its choice
              // back in ``data.mode``. Trusting the local toggle would
              // miss auto-promoted deep answers.
              if (data.mode === "deep" && data.content && convoId) {
                try {
                  const section = parseDeepModeToNotes(
                    data.content,
                    placeholder.id,
                    convoId,
                  );
                  useNotesStore.getState().addSection(section);

                  // Phase 4 — auto-generate the section image in
                  // the background. We deliberately *don't* await
                  // this: the section is already visible, the user
                  // can keep typing, and the image just fades in
                  // when ready (typically 5–15s). On failure we
                  // swallow silently — the section stays imageless
                  // rather than showing an error chrome the user
                  // can't act on.
                  const sectionId = section.id;
                  if (data.image_prompt) {
                    chatApi
                      .generateImage(data.image_prompt)
                      .then((res) => {
                        if (res?.image?.url) {
                          useNotesStore
                            .getState()
                            .setSectionImage(sectionId, res.image.url);
                        }
                      })
                      .catch((err) => {
                        // eslint-disable-next-line no-console
                        console.warn(
                          "[notes] image generation failed for section",
                          sectionId,
                          err,
                        );
                      });
                  }
                } catch {
                  // Notes parser failure is non-fatal — the chat
                  // answer is already rendered, just no notebook
                  // section gets created this turn.
                }
              }
            },
            onError: (msg) => {
              useToastStore.getState().notify({
                type: "error",
                title: "Stream failed",
                message: msg,
                durationMs: 6500,
              });
              updateLastMessageFull(convoId!, {
                content:
                  "The assistant could not be reached. " + msg,
                isStreaming: false,
              });
            },
          },
          abortRef.current.signal,
        );
      } catch (e) {
        // Don't toast on AbortError — the user pressed Stop, that's a
        // deliberate cancel, not a failure.
        if (!(e instanceof DOMException && e.name === "AbortError")) {
          toastError(e, "Chat backend unreachable");
        }
        updateLastMessageFull(convoId!, {
          content:
            "The assistant could not be reached. Start the backend at http://localhost:8000 and try again.",
          isStreaming: false,
        });
      } finally {
        setStreaming(false);
      }
    },
    [
      activeConversation,
      activeConversationId,
      addMessage,
      appendToLastMessage,
      chatMode,
      createConversation,
      isStreaming,
      mergeBrief,
      setStreaming,
      updateLastMessageFull,
    ],
  );

  const stop = () => {
    abortRef.current?.abort();
    setStreaming(false);
  };

  return (
    <div className="min-h-screen w-full flex flex-col bg-paper">
      <BackendHealthBanner />
      <TopBar onToggleSidebar={toggleSidebar} />

      <div className="flex-1 flex min-h-0 relative">
        {/* Mobile backdrop — dismisses the slide-over sidebar on tap.
            Only renders below md when the sidebar is open. */}
        {sidebarOpen ? (
          <div
            className="fixed inset-0 bg-ink-deep/30 z-30 md:hidden"
            onClick={toggleSidebar}
            aria-hidden="true"
          />
        ) : null}
        {sidebarOpen ? (
          <ConversationSidebar
            conversations={conversations as ConversationLite[]}
            activeId={activeConversationId}
            onSelect={setActiveConversation}
            onNew={() => createConversation()}
            onDelete={deleteConversation}
          />
        ) : null}

        <main className="flex-1 flex flex-col min-w-0 border-l border-hairline">
          <div
            ref={transcriptRef}
            className="flex-1 overflow-y-auto draft-scroll"
          >
            {activeConversation && activeConversation.messages.length > 0 ? (
              <Transcript
                messages={activeConversation.messages}
                conversationId={activeConversation.id}
                onEditUserMessage={setInput}
              />
            ) : (
              <EmptyHero onPick={(p) => submit(p)} />
            )}
          </div>

          <PromptInput
            value={input}
            onChange={setInput}
            onSubmit={() => submit(input)}
            onStop={stop}
            mode={chatMode}
            streaming={isStreaming}
            setMode={setChatMode}
          />
        </main>

        {/* NotesSidebar manages its own slide-in/slide-out via
            framer-motion's AnimatePresence, so we always mount it and
            let `isOpen` drive visibility. Deep mode flips
            notesPanelOpen to true automatically (see useEffect above). */}
        <NotesSidebar
          isOpen={notesPanelOpen}
          onClose={() => setNotesPanelOpen(false)}
        />
      </div>
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────────────

function TopBar({ onToggleSidebar }: { onToggleSidebar: () => void }) {
  return (
    <header className="border-b border-hairline bg-paper">
      <div className="px-5 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={onToggleSidebar}
            className="text-ink-soft hover:text-ink transition-colors p-1.5 -ml-1.5 rounded-md hover:bg-paper-soft"
            aria-label="Toggle conversations sidebar"
            aria-expanded={undefined}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 18 18"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                d="M2.5 4.5h13M2.5 9h13M2.5 13.5h13"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
              />
            </svg>
          </button>
          <Link
            href="/chat"
            className="text-[1.05rem] text-ink-deep tracking-tight font-semibold leading-none"
          >
            KATHA AI
          </Link>
        </div>
        <nav className="flex items-center gap-2">
          <Link href="/chat" className="slide-pill" data-active="true">
            Chat
          </Link>
          <Link href="/design" className="slide-pill" data-active="false">
            Design
          </Link>
        </nav>
      </div>
    </header>
  );
}

/* Slim shape ConversationSidebar needs from each conversation. We
   don't need messages/timestamps for *every* field — just title,
   updatedAt (for date-grouping), and the optional project binding. */
type ConversationLite = {
  id: string;
  title: string;
  updatedAt: string;
  projectId?: string;
  projectName?: string;
};

const DATE_GROUPS = ["Today", "Yesterday", "Previous 7 days", "Older"] as const;
type DateGroup = (typeof DATE_GROUPS)[number];

/* Bucket conversations into date groups by their updatedAt. The
   architect's mental model is "what did I work on today / yesterday
   / last week" — same as every other chat app. Date grouping wins
   over project grouping at small scale (we don't have 20+ chats per
   project yet); project context lives in a per-item caption instead. */
function groupConversationsByDate(
  list: ConversationLite[],
): Record<DateGroup, ConversationLite[]> {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekAgo = new Date(today.getTime() - 7 * 86400000);

  const groups: Record<DateGroup, ConversationLite[]> = {
    Today: [],
    Yesterday: [],
    "Previous 7 days": [],
    Older: [],
  };
  for (const c of list) {
    const d = new Date(c.updatedAt);
    if (d >= today) groups["Today"].push(c);
    else if (d >= yesterday) groups["Yesterday"].push(c);
    else if (d >= weekAgo) groups["Previous 7 days"].push(c);
    else groups["Older"].push(c);
  }
  return groups;
}

function timeAgoShort(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d`;
  return new Date(dateStr).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function ConversationSidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
}: {
  conversations: ConversationLite[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}) {
  const sorted = useMemo(
    () =>
      [...conversations].sort(
        (a, b) =>
          new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
      ),
    [conversations],
  );
  const groups = useMemo(() => groupConversationsByDate(sorted), [sorted]);

  return (
    <aside className="w-64 shrink-0 bg-paper-soft flex flex-col fixed inset-y-0 left-0 z-40 shadow-lg md:static md:z-auto md:shadow-none">
      <div className="px-4 py-4">
        <button
          type="button"
          onClick={onNew}
          className="w-full text-left px-3 py-2 border border-hairline bg-paper hover:border-graphite hover:bg-paper-deep/40 rounded-md transition-colors flex items-center gap-2 text-sm text-ink-deep"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <path
              d="M7 2.5v9M2.5 7h9"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
            />
          </svg>
          New chat
        </button>
      </div>
      <div className="flex-1 overflow-y-auto draft-scroll px-2 pb-3">
        {sorted.length === 0 ? (
          <div className="px-3 py-4 text-sm text-ink-mute">
            No conversations yet.
          </div>
        ) : (
          DATE_GROUPS.map((label) => {
            const items = groups[label];
            if (items.length === 0) return null;
            return (
              <div key={label} className="mt-3 first:mt-0">
                <p className="px-3 py-1.5 font-mono text-[10.5px] uppercase tracking-tagged text-ink-mute">
                  {label}
                </p>
                <div className="space-y-0.5">
                  {items.map((c) => {
                    const active = c.id === activeId;
                    const projectName = c.projectName?.trim();
                    return (
                      <div
                        key={c.id}
                        className={`group px-3 py-2 cursor-pointer rounded-md transition-colors ${
                          active
                            ? "bg-paper-deep"
                            : "hover:bg-paper-deep/50"
                        }`}
                        onClick={() => onSelect(c.id)}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span
                            className={`text-[14.5px] truncate flex-1 tracking-tight leading-snug ${
                              active
                                ? "text-ink-deep font-semibold"
                                : "text-ink-soft font-medium"
                            }`}
                          >
                            {c.title || "Untitled"}
                          </span>
                          <span className="group-hover:hidden text-[11.5px] text-ink-mute font-mono tracking-wider tnum shrink-0">
                            {timeAgoShort(c.updatedAt)}
                          </span>
                          <button
                            type="button"
                            className="hidden group-hover:flex items-center justify-center w-6 h-6 rounded-md text-ink-mute hover:text-pencil hover:bg-pencil-bg transition-colors shrink-0"
                            onClick={(e) => {
                              e.stopPropagation();
                              onDelete(c.id);
                            }}
                            aria-label="Delete conversation"
                          >
                            <svg
                              width="13"
                              height="13"
                              viewBox="0 0 13 13"
                              fill="none"
                              xmlns="http://www.w3.org/2000/svg"
                            >
                              <path
                                d="M3 3l7 7M10 3l-7 7"
                                stroke="currentColor"
                                strokeWidth="1.4"
                                strokeLinecap="round"
                              />
                            </svg>
                          </button>
                        </div>
                        {projectName ? (
                          <p
                            className="mt-1 truncate font-mono text-[10.5px] uppercase tracking-tagged text-ink-mute"
                            title={`Project: ${projectName}`}
                          >
                            <span className="mr-1">▸</span>
                            {projectName}
                          </p>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
}

/* Compact mode toggle — lives below the prompt input (Claude / ChatGPT
   register). Pills are subtle: ink-mute at rest, paper-deep + ink-deep
   when active. The placeholder text in the textarea above carries the
   mode's tagline, so no inline subtitle is needed here. */
function ModeToggle({
  mode,
  setMode,
}: {
  mode: ChatMode;
  setMode: (m: ChatMode) => void;
}) {
  return (
    <div className="inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-paper-soft border border-hairline">
      {MODES.map((m) => {
        const active = m.id === mode;
        return (
          <button
            key={m.id}
            type="button"
            onClick={() => setMode(m.id)}
            title={m.tagline}
            className={`px-3 py-1 rounded-md text-[12.5px] font-medium transition-colors ${
              active
                ? "bg-paper text-ink-deep shadow-card"
                : "text-ink-mute hover:text-ink"
            }`}
          >
            {m.label}
          </button>
        );
      })}
    </div>
  );
}

function EmptyHero({ onPick }: { onPick: (prompt: string) => void }) {
  const suggestions = [
    "What is the NBC minimum door width for a residential entry?",
    "Walk me through a contemporary 3 BHK kitchen layout.",
    "Compare walnut vs teak for a dining table top.",
    "Explain ECBC envelope U-value targets for warm-humid climates.",
  ];
  return (
    <div className="px-6 md:px-10 py-12 max-w-chat mx-auto">
      <h1 className="text-[1.875rem] md:text-[2.125rem] text-ink-deep leading-[1.15] tracking-[-0.02em] font-semibold">
        Good to see you, architect.
      </h1>
      <p className="mt-4 text-ink-soft text-[15px] leading-relaxed max-w-xl">
        Ask anything about codes, materials, ergonomics, structural logic,
        manufacturing, or cost. Switch to Deep for a long-form
        conversation with a notes pane that writes itself.
      </p>

      <div className="mt-7 space-y-2">
        {suggestions.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onPick(s)}
            className="w-full text-left px-4 py-2.5 border border-hairline bg-paper hover:bg-paper-soft hover:border-graphite rounded-md transition-colors text-[14.5px] text-ink leading-snug"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

function Transcript({
  messages,
  conversationId,
  onEditUserMessage,
}: {
  messages: Message[];
  conversationId: string;
  onEditUserMessage: (content: string) => void;
}) {
  return (
    <div className="px-6 md:px-10 py-7 max-w-chat mx-auto space-y-5">
      {messages.map((m) => (
        <MessageRow
          key={m.id}
          message={m}
          conversationId={conversationId}
          onEditUserMessage={onEditUserMessage}
        />
      ))}
    </div>
  );
}

function MessageRow({
  message,
  conversationId,
  onEditUserMessage,
}: {
  message: Message;
  conversationId: string;
  onEditUserMessage: (content: string) => void;
}) {
  const isUser = message.role === "user";
  if (isUser) {
    return (
      <div id={`msg-${message.id}`} className="anim-fade-in group/msg scroll-mt-20">
        <div className="mb-2 flex items-center justify-between">
          <span className="font-mono text-[11px] tracking-tagged uppercase text-ink-mute">
            You
          </span>
          <MessageActions
            message={message}
            conversationId={conversationId}
            onEdit={() => onEditUserMessage(message.content)}
          />
        </div>
        <div className="text-ink-deep text-[1.0625rem] leading-relaxed whitespace-pre-wrap">
          {message.content}
        </div>
      </div>
    );
  }
  return (
    <AssistantMessage message={message} conversationId={conversationId} />
  );
}

/* MessageActions — quiet hover-revealed toolbar on every message.
 *
 * Behaviours:
 *   • Copy — copies plain message text. ✓ tick for 1.5s on success.
 *   • Cite — copies a deep link (#msg-{id}) so the architect can
 *     paste a pointer back into Notes, a doc, or another chat.
 *   • Save — assistant only. Parses the message via
 *     ``parseDeepModeToNotes`` (handles both Deep-formatted answers
 *     and plain prose fallback) and adds a NoteSection. Same path the
 *     Deep-Mode auto-save uses.
 *   • Edit — user only. Re-populates the prompt input with the user's
 *     text so they can tweak and re-send. We deliberately do NOT
 *     mutate history; the original message stays in the log.
 *
 * Register: pencil-bg on hover, ink-mute → ink-deep contrast lift,
 * mono labels. Keep it whisper-quiet — visible only on hover, no
 * persistent chrome that competes with the prose.
 */
function MessageActions({
  message,
  conversationId,
  onEdit,
}: {
  message: Message;
  conversationId: string;
  onEdit?: () => void;
}) {
  const isUser = message.role === "user";
  const [copied, setCopied] = useState<"text" | "link" | null>(null);
  const [saved, setSaved] = useState(false);

  const copyText = async () => {
    try {
      await navigator.clipboard.writeText(message.content || "");
      setCopied("text");
      setTimeout(() => setCopied(null), 1500);
    } catch {
      // Clipboard may be denied (insecure context, browser refuses).
      // Surface as a quiet warning so the architect knows why the
      // inline ✓ never appeared.
      useToastStore.getState().notify({
        type: "warning",
        title: "Copy blocked",
        message: "The browser denied clipboard access. Select the text manually.",
      });
    }
  };

  const copyCitation = async () => {
    try {
      const url = `${window.location.href.split("#")[0]}#msg-${message.id}`;
      await navigator.clipboard.writeText(url);
      setCopied("link");
      setTimeout(() => setCopied(null), 1500);
    } catch {
      useToastStore.getState().notify({
        type: "warning",
        title: "Copy blocked",
        message: "The browser denied clipboard access.",
      });
    }
  };

  const saveToNotes = () => {
    try {
      const section = parseDeepModeToNotes(
        message.content || "",
        message.id,
        conversationId,
      );
      useNotesStore.getState().addSection(section);
      // Open the notes panel so the architect sees the new section
      // land in the right rail — closes the loop visually.
      useNotesStore.getState().setNotesPanelOpen(true);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
      useToastStore.getState().notify({
        type: "success",
        title: "Saved to notes",
        message: section.title.slice(0, 60),
        durationMs: 2800,
      });
    } catch (e) {
      toastError(e, "Could not save note");
    }
  };

  // Buttons share styling. Each is a tiny mono-labelled chip that
  // appears only when the parent group is hovered, keeping the prose
  // surface quiet at rest.
  const btn =
    "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-tagged text-ink-mute hover:text-ink-deep hover:bg-paper-soft transition-colors";

  return (
    <div className="opacity-0 group-hover/msg:opacity-100 focus-within:opacity-100 transition-opacity flex items-center gap-0.5">
      <button onClick={copyText} className={btn} title="Copy message text">
        {copied === "text" ? <Check size={11} className="text-olive" /> : <Copy size={11} />}
        {copied === "text" ? "Copied" : "Copy"}
      </button>
      <button onClick={copyCitation} className={btn} title="Copy link to this message">
        {copied === "link" ? <Check size={11} className="text-olive" /> : <Link2 size={11} />}
        {copied === "link" ? "Linked" : "Cite"}
      </button>
      {!isUser ? (
        <button onClick={saveToNotes} className={btn} title="Save as a note">
          {saved ? <Check size={11} className="text-olive" /> : <BookmarkPlus size={11} />}
          {saved ? "Saved" : "Save"}
        </button>
      ) : null}
      {isUser && onEdit ? (
        <button onClick={onEdit} className={btn} title="Edit and re-send">
          <Pencil size={11} />
          Edit
        </button>
      ) : null}
    </div>
  );
}

/* AssistantMessage — the architect-specific reply surface.
 *
 * Three things distinguish it from a generic AI-chat bubble:
 *
 *   1. **Data callouts** — numbers with units (900mm, W/m²K) and code
 *      references (NBC §4.2.1) get auto-wrapped in pencil-coloured
 *      spans so the eye scans them as data, not prose.
 *
 *   2. **Sidenote citations** — on wide viewports (≥ lg) the
 *      `referenceLinks` move from a "Sources" footer into the
 *      right-hand gutter, anchored to the paragraph by a small
 *      numeric marker (①②③). The architect reads prose on the left,
 *      sources on the right — Tufte-style, the standard architectural
 *      register for spec documents.
 *
 *   3. **Footer fallback** — on narrow viewports the gutter collapses
 *      back to the legacy bottom-of-message Sources block so phones /
 *      narrow windows aren't broken.
 */
function AssistantMessage({
  message,
  conversationId,
}: {
  message: Message;
  conversationId: string;
}) {
  const refs = message.referenceLinks ?? [];

  /* Anchor each reference to its paragraph by content rather than by
     render order — the previous useRef-based counter was unreliable
     because React 18 strict-mode double-invokes function components
     in dev, and ReactMarkdown's paragraph renders aren't strictly
     sequential during a commit.

     Honest approximation: the first ref tags the first paragraph,
     the second tags the second, etc. (1-to-1 by index). We compute
     the paragraph-text → ref-index map up front from the message
     content; the paragraph renderer then looks up by the rendered
     paragraph's joined plain text. Stable across re-renders. */
  const paragraphRefMap = useMemo(() => {
    const map = new Map<string, number>();
    if (!message.content) return map;
    // Markdown paragraphs are blank-line separated. Normalise inner
    // whitespace + lowercase the lookup key so trivial formatting
    // differences (re-runs, partial streams) still match.
    const paragraphs = message.content
      .split(/\n\s*\n/)
      .map((p) => p.trim())
      .filter(Boolean);
    paragraphs.forEach((p, i) => {
      if (i < refs.length) {
        map.set(normaliseParagraphKey(p), i);
      }
    });
    return map;
  }, [message.content, refs.length]);

  /* Custom paragraph renderer:
       1. Run the paragraph's children through processChildren so
          data + code-ref callouts get spans wrapped in.
       2. Append the numbered marker for whichever reference (if any)
          this paragraph's plain text maps to. */
  const paragraphRenderer = (props: { children?: React.ReactNode }) => {
    const processed = processChildren(props.children);
    const plain = extractPlainText(props.children);
    const refIdx = paragraphRefMap.get(normaliseParagraphKey(plain));
    return (
      <p>
        {processed}
        {refIdx !== undefined && refs[refIdx] ? (
          <a
            href={refs[refIdx].url}
            target="_blank"
            rel="noreferrer"
            className="ref-marker hover:text-pencil-soft"
            aria-label={`Source: ${refs[refIdx].title}`}
            title={refs[refIdx].title}
          >
            {refMarker(refIdx)}
          </a>
        ) : null}
      </p>
    );
  };

  return (
    <div id={`msg-${message.id}`} className="anim-fade-in group/msg scroll-mt-20">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-mono text-[11px] tracking-tagged uppercase text-ink-mute">
          KATHA AI
        </span>
        {/* Suppress toolbar while the assistant is still streaming —
            Copy/Save on a half-finished message gives garbage. */}
        {!message.isStreaming ? (
          <MessageActions message={message} conversationId={conversationId} />
        ) : null}
      </div>
      {/* lg+: 2-column grid with prose on the left and sidenotes
          gutter on the right. Below lg the gutter is hidden and the
          footer fallback renders the Sources block. */}
      <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_14rem] lg:gap-8">
        <div className="message-prose min-w-0">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{ p: paragraphRenderer }}
          >
            {message.content || (message.isStreaming ? " " : "")}
          </ReactMarkdown>
          {message.isStreaming ? <TypingDots /> : null}
          {message.suggestions && message.suggestions.length > 0 ? (
            <div className="mt-5 flex flex-wrap gap-2">
              {message.suggestions.map((s) => (
                <span
                  key={s}
                  className="text-[13px] text-ink-soft border border-hairline px-2.5 py-1 rounded-md bg-paper-soft"
                >
                  {s}
                </span>
              ))}
            </div>
          ) : null}
          {/* Footer fallback — only visible below lg so the
              architect on a phone / narrow window still sees the
              citation list. On lg+ the gutter handles this. */}
          {refs.length > 0 ? (
            <div className="mt-5 lg:hidden">
              <SectionTag>Sources</SectionTag>
              <ul className="mt-2 space-y-1">
                {refs.map((r, i) => (
                  <li key={r.url} className="text-[13px] flex items-baseline gap-2">
                    <span className="font-mono text-pencil text-[11px] shrink-0">
                      {refMarker(i)}
                    </span>
                    <a
                      href={r.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-pencil hover:text-pencil-soft underline underline-offset-2"
                    >
                      {r.title}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
        {/* Right gutter — Tufte-style sidenotes. Sticky top so the
            list stays in view as the architect scrolls long replies.
            Hidden below lg. */}
        {refs.length > 0 ? (
          <aside
            className="hidden lg:block"
            aria-label="Citation sidenotes"
          >
            <div className="sticky top-4">
              <SectionTag>Sources</SectionTag>
              <ul className="mt-2 space-y-3">
                {refs.map((r, i) => (
                  <li key={r.url} className="text-[12px] leading-snug">
                    <a
                      href={r.url}
                      target="_blank"
                      rel="noreferrer"
                      className="block group"
                    >
                      <span className="flex items-baseline gap-2">
                        <span className="font-mono text-pencil text-[11px] shrink-0">
                          {refMarker(i)}
                        </span>
                        <span className="text-ink-deep group-hover:text-pencil transition-colors">
                          {r.title}
                        </span>
                      </span>
                      {r.type && r.type !== "other" ? (
                        <span className="ml-5 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-mute">
                          {r.type}
                        </span>
                      ) : null}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </aside>
        ) : null}
      </div>
    </div>
  );
}

function TypingDots() {
  return (
    <span className="inline-flex items-center gap-1 ml-1 align-middle">
      <span className="typing-dot inline-block w-1.5 h-1.5 rounded-full bg-ink-mute" />
      <span className="typing-dot inline-block w-1.5 h-1.5 rounded-full bg-ink-mute" />
      <span className="typing-dot inline-block w-1.5 h-1.5 rounded-full bg-ink-mute" />
    </span>
  );
}

function PromptInput({
  value,
  onChange,
  onSubmit,
  onStop,
  mode,
  streaming,
  setMode,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  mode: ChatMode;
  streaming: boolean;
  setMode: (m: ChatMode) => void;
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 240) + "px";
  }, [value]);

  return (
    <div className="border-t border-hairline bg-paper px-6 md:px-10 py-4">
      <div className="max-w-chat mx-auto">
        <div className="border border-hairline rounded-xl bg-paper-soft/60 p-3 flex items-end gap-3 focus-within:border-graphite transition-colors">
          <textarea
            ref={ref}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={
              mode === "quick"
                ? "Ask one thing…"
                : mode === "deep"
                ? "Open a discussion. Tell me what you're working on…"
                : "Message KATHA AI…"
            }
            rows={1}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSubmit();
              }
            }}
            className="flex-1 resize-none outline-none bg-transparent text-ink placeholder:text-ink-mute leading-relaxed py-1.5 text-[15px]"
            disabled={streaming}
          />
          {streaming ? (
            <button
              type="button"
              onClick={onStop}
              className="shrink-0 text-[13px] font-medium px-3 py-1.5 bg-brick text-paper hover:bg-brick/85 rounded-md transition-colors"
              aria-label="Stop streaming"
            >
              Stop
            </button>
          ) : (
            <button
              type="button"
              onClick={onSubmit}
              disabled={!value.trim()}
              className="shrink-0 text-[13px] font-medium px-3 py-1.5 bg-ink-deep text-paper hover:bg-ink rounded-md transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              aria-label="Send message"
            >
              Send
            </button>
          )}
        </div>
        {/* Mode toggle + keyboard hint row — sits below the input the
            way ChatGPT / Claude / Perplexity place it. Active mode
            controls the textarea placeholder, so no inline subtitle. */}
        <div className="mt-3 flex items-center justify-between gap-3">
          <ModeToggle mode={mode} setMode={setMode} />
          <span className="text-[11px] text-ink-mute hidden sm:block">
            ↵ to send · ⇧↵ for newline
          </span>
        </div>
      </div>
    </div>
  );
}

