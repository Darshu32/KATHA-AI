"use client";

/* MVP 1 — Chat workspace.
 * Editorial Claude-inspired layout: quiet left sidebar of conversations,
 * centered conversation column with serif headlines + sans body, optional
 * right notes pane that auto-opens in Deep mode. Minimal chrome. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useChatStore, useNotesStore } from "@/lib/store";
import { chat as chatApi } from "@/lib/api-client";
import { parseDeepModeToNotes } from "@/lib/notes-parser";
import { useNotesPersist } from "@/lib/use-notes-persist";
import type { ChatMode, Message } from "@/lib/types";
import {
  Annotation,
  BrassRule,
  PaperCard,
  SectionTag,
} from "@/components/primitives";

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
              updateLastMessageFull(convoId!, {
                content:
                  "The assistant could not be reached. " + msg,
                isStreaming: false,
              });
            },
          },
          abortRef.current.signal,
        );
      } catch {
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
      <TopBar onToggleSidebar={toggleSidebar} />

      <div className="flex-1 flex min-h-0">
        {sidebarOpen ? (
          <ConversationSidebar
            conversations={conversations}
            activeId={activeConversationId}
            onSelect={setActiveConversation}
            onNew={() => createConversation()}
            onDelete={deleteConversation}
          />
        ) : null}

        <main className="flex-1 flex flex-col min-w-0 border-l border-hairline">
          <ModeBar mode={chatMode} setMode={setChatMode} />

          <div
            ref={transcriptRef}
            className="flex-1 overflow-y-auto draft-scroll"
          >
            {activeConversation && activeConversation.messages.length > 0 ? (
              <Transcript messages={activeConversation.messages} />
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
          />
        </main>

        {notesPanelOpen ? (
          <NotesPane onClose={() => setNotesPanelOpen(false)} />
        ) : null}
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
            aria-label="toggle conversations"
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
            Katha
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

function ConversationSidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
}: {
  conversations: { id: string; title: string }[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}) {
  return (
    <aside className="w-64 shrink-0 bg-paper-soft flex flex-col">
      <div className="px-4 py-4">
        <button
          type="button"
          onClick={onNew}
          className="w-full text-left px-3 py-2 border border-hairline bg-paper hover:border-graphite hover:bg-paper-deep/40 rounded-md transition-colors flex items-center gap-2 text-sm text-ink"
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
      <div className="px-4 pb-2">
        <SectionTag>Recent</SectionTag>
      </div>
      <div className="flex-1 overflow-y-auto draft-scroll px-2 pb-3 space-y-0.5">
        {conversations.length === 0 ? (
          <div className="px-3 py-4 text-sm text-ink-mute">
            No conversations yet.
          </div>
        ) : (
          conversations.map((c) => {
            const active = c.id === activeId;
            return (
              <div
                key={c.id}
                className={`group px-3 py-2 cursor-pointer flex items-center justify-between gap-2 rounded-md transition-colors ${
                  active
                    ? "bg-paper-deep text-ink-deep"
                    : "hover:bg-paper-deep/50 text-ink"
                }`}
                onClick={() => onSelect(c.id)}
              >
                <span className="text-sm truncate flex-1">
                  {c.title || "Untitled"}
                </span>
                <button
                  type="button"
                  className="opacity-0 group-hover:opacity-100 text-ink-mute hover:text-brick transition-opacity"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(c.id);
                  }}
                  aria-label="delete"
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
            );
          })
        )}
      </div>
    </aside>
  );
}

function ModeBar({
  mode,
  setMode,
}: {
  mode: ChatMode;
  setMode: (m: ChatMode) => void;
}) {
  return (
    <div className="px-6 py-3 border-b border-hairline flex items-center gap-2">
      {MODES.map((m) => (
        <button
          key={m.id}
          type="button"
          className="slide-pill"
          data-active={m.id === mode}
          onClick={() => setMode(m.id)}
        >
          {m.label}
        </button>
      ))}
      <span className="ml-2 text-ink-mute text-[13px]">
        {MODES.find((m) => m.id === mode)?.tagline}
      </span>
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
    <div className="px-6 md:px-10 py-20 max-w-chat mx-auto">
      <h1 className="text-[2rem] md:text-[2.25rem] text-ink-deep leading-[1.15] tracking-[-0.02em] font-semibold">
        Good to see you, architect.
      </h1>
      <p className="mt-5 text-ink-soft text-[15px] leading-relaxed max-w-xl">
        Ask anything about codes, materials, ergonomics, structural logic,
        manufacturing, or cost. Switch to Deep for a long-form
        conversation with a notes pane that writes itself.
      </p>

      <div className="mt-10 space-y-2">
        {suggestions.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onPick(s)}
            className="w-full text-left px-4 py-3 border border-hairline bg-paper hover:bg-paper-soft hover:border-graphite rounded-md transition-colors text-[15px] text-ink leading-snug"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

function Transcript({ messages }: { messages: Message[] }) {
  return (
    <div className="px-6 md:px-10 py-10 max-w-chat mx-auto space-y-8">
      {messages.map((m) => (
        <MessageRow key={m.id} message={m} />
      ))}
    </div>
  );
}

function MessageRow({ message }: { message: Message }) {
  const isUser = message.role === "user";
  return (
    <div className="anim-fade-in">
      <div className="mb-2">
        <span className="font-mono text-[11px] tracking-tagged uppercase text-ink-mute">
          {isUser ? "You" : "Katha"}
        </span>
      </div>
      <div
        className={
          isUser
            ? "text-ink-deep text-[1.0625rem] leading-relaxed whitespace-pre-wrap"
            : "message-prose"
        }
      >
        {isUser ? (
          message.content
        ) : (
          <>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
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
            {message.referenceLinks && message.referenceLinks.length > 0 ? (
              <div className="mt-5">
                <SectionTag>Sources</SectionTag>
                <ul className="mt-2 space-y-1">
                  {message.referenceLinks.map((r) => (
                    <li key={r.url} className="text-[13px]">
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
          </>
        )}
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
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  mode: ChatMode;
  streaming: boolean;
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
                : "Message Katha…"
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
              aria-label="stop"
            >
              Stop
            </button>
          ) : (
            <button
              type="button"
              onClick={onSubmit}
              disabled={!value.trim()}
              className="shrink-0 text-[13px] font-medium px-3 py-1.5 bg-ink-deep text-paper hover:bg-ink rounded-md transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              aria-label="send"
            >
              Send
            </button>
          )}
        </div>
        <div className="mt-2 px-1 text-[11px] text-ink-mute">
          ↵ to send · ⇧↵ for newline
        </div>
      </div>
    </div>
  );
}

function NotesPane({ onClose }: { onClose: () => void }) {
  return (
    <aside className="w-[22rem] shrink-0 bg-paper-soft border-l border-hairline flex flex-col">
      <div className="px-5 py-4 border-b border-hairline flex items-center justify-between">
        <SectionTag>Notes</SectionTag>
        <button
          type="button"
          onClick={onClose}
          className="text-ink-mute hover:text-ink transition-colors"
          aria-label="close notes"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <path
              d="M3.5 3.5l7 7M10.5 3.5l-7 7"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </div>
      <div className="flex-1 overflow-y-auto draft-scroll px-5 py-5">
        <PaperCard className="p-5">
          <div className="flex items-center justify-between">
            <h3 className="text-[15px] text-ink-deep font-semibold tracking-[-0.01em]">
              Session notes
            </h3>
            <Annotation>auto-generated</Annotation>
          </div>
          <BrassRule />
          <p className="mt-3 text-ink-soft text-sm leading-relaxed">
            When you switch to <em>Deep</em> mode and start a conversation,
            this pane will write itself — sectioning topics, citing sources,
            and flagging open questions.
          </p>
          <div className="mt-4">
            <SectionTag>What appears here</SectionTag>
            <ul className="mt-3 space-y-2 text-sm text-ink">
              <li className="flex items-start">
                <span className="status-dot status-dot--ok mt-1.5" />
                <span>decisions reached during this conversation</span>
              </li>
              <li className="flex items-start">
                <span className="status-dot status-dot--src mt-1.5" />
                <span>source citations and references</span>
              </li>
              <li className="flex items-start">
                <span className="status-dot status-dot--info mt-1.5" />
                <span>next-step suggestions</span>
              </li>
              <li className="flex items-start">
                <span className="status-dot status-dot--warn mt-1.5" />
                <span>open questions left to resolve</span>
              </li>
            </ul>
          </div>
        </PaperCard>
      </div>
    </aside>
  );
}
