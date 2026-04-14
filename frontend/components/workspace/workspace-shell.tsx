"use client";

import { useMemo, useCallback, useRef, useEffect } from "react";
import { useChatStore, useWorkspaceStore } from "@/lib/store";
import { chat } from "@/lib/api-client";
import type { Message } from "@/lib/types";
import Sidebar from "../sidebar/sidebar";
import ChatHeader from "../chat/chat-header";
import ChatArea from "../chat/chat-area";
import PromptInput from "../chat/prompt-input";
import ImageWorkspaceShell from "./image-workspace-shell";

export default function WorkspaceShell() {
  const {
    conversations,
    activeConversationId,
    isStreaming,
    sidebarOpen,
    chatMode,
    createConversation,
    addMessage,
    appendToLastMessage,
    updateLastMessageFull,
    setStreaming,
    toggleSidebar,
    deleteConversation,
  } = useChatStore();

  const activeWorkspace = useWorkspaceStore((s) => s.activeWorkspace);
  const abortRef = useRef<AbortController | null>(null);

  const activeConversation = useMemo(
    () => conversations.find((c) => c.id === activeConversationId) ?? null,
    [conversations, activeConversationId],
  );

  const handleSend = useCallback(
    async (text: string) => {
      let convId = activeConversationId;
      if (!convId) {
        convId = createConversation();
      }

      // Add user message
      const userMessage: Message = {
        id: crypto.randomUUID(),
        role: "user",
        content: text,
        timestamp: new Date().toISOString(),
      };
      addMessage(convId, userMessage);

      // Add empty assistant message for streaming
      const assistantMessage: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
        isStreaming: true,
      };
      addMessage(convId, assistantMessage);
      setStreaming(true);

      // Build conversation history from existing messages (excluding the new ones)
      const currentConv = useChatStore.getState().conversations.find((c) => c.id === convId);
      const history = (currentConv?.messages ?? [])
        .slice(0, -2) // exclude the user + assistant messages we just added
        .map((m) => ({ role: m.role, content: m.content }));

      // Abort any previous stream
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      const capturedConvId = convId;

      try {
        await chat.stream(
          text,
          history,
          chatMode === "auto" ? null : chatMode,
          {
            onToken: (token) => {
              appendToLastMessage(capturedConvId, token);
            },
            onDone: async (data) => {
              const currentConvState = useChatStore.getState().conversations.find((c) => c.id === capturedConvId);
              const lastMsg = currentConvState?.messages[currentConvState.messages.length - 1];
              const finalContent = data.content || lastMsg?.content || "";

              // Mode-aware media fetching
              let images: Message["images"] = undefined;
              let video: Message["video"] = undefined;
              let youtubeLinks: Message["youtubeLinks"] = undefined;
              let researchPapers: Message["researchPapers"] = undefined;
              let referenceLinks: Message["referenceLinks"] = undefined;

              const isDeepMode = data.mode === "deep";

              try {
                if (isDeepMode) {
                  // Deep Mode: AI image + YouTube tutorials + research papers + reference links
                  const promises = await Promise.allSettled([
                    data.image_prompt ? chat.generateImage(data.image_prompt) : Promise.resolve(null),
                    data.youtube_query ? chat.searchYoutube(data.youtube_query, 3, "medium") : Promise.resolve(null),
                    data.research_query ? chat.searchPapers(data.research_query, 3) : Promise.resolve(null),
                  ]);

                  // AI image
                  const imgResult = promises[0].status === "fulfilled" ? promises[0].value : null;
                  if (imgResult && "image" in imgResult && imgResult.image) {
                    images = [{ ...imgResult.image, type: "ai-image" as const, source: imgResult.image.source || "nano-banana" }];
                  }

                  // YouTube tutorials
                  const ytResult = promises[1].status === "fulfilled" ? promises[1].value : null;
                  if (ytResult && "videos" in ytResult && ytResult.videos.length > 0) {
                    youtubeLinks = ytResult.videos.map((v) => ({ ...v, type: "youtube" as const, source: "youtube" }));
                  }

                  // Research papers
                  const paperResult = promises[2].status === "fulfilled" ? promises[2].value : null;
                  if (paperResult && "papers" in paperResult && paperResult.papers.length > 0) {
                    researchPapers = paperResult.papers.map((p) => ({ ...p, type: "paper" as const }));
                  }

                  // Reference links from AI
                  if (data.reference_links?.length) {
                    referenceLinks = data.reference_links.map((l) => ({
                      ...l,
                      type: (l.type || "other") as "article" | "standard" | "documentation" | "other",
                    }));
                  }
                } else {
                  // Quick Mode: AI image + YouTube short clip
                  const promises = await Promise.allSettled([
                    data.image_prompt ? chat.generateImage(data.image_prompt) : Promise.resolve(null),
                    data.video_query ? chat.searchYoutube(data.video_query, 1, "short") : Promise.resolve(null),
                  ]);

                  // AI image
                  const imgResult = promises[0].status === "fulfilled" ? promises[0].value : null;
                  if (imgResult && "image" in imgResult && imgResult.image) {
                    images = [{ ...imgResult.image, type: "ai-image" as const, source: imgResult.image.source || "nano-banana" }];
                  }

                  // YouTube short clip
                  const ytResult = promises[1].status === "fulfilled" ? promises[1].value : null;
                  if (ytResult && "videos" in ytResult && ytResult.videos.length > 0) {
                    video = { ...ytResult.videos[0], type: "youtube" as const, source: "youtube" };
                  }
                }
              } catch {
                // Media fetch failed — continue with text only
              }

              updateLastMessageFull(capturedConvId, {
                content: finalContent,
                isStreaming: false,
                suggestions: data.suggestions,
                images,
                video,
                youtubeLinks,
                researchPapers,
                referenceLinks,
                mode: data.mode as Message["mode"],
              });
              setStreaming(false);
            },
            onError: (error) => {
              updateLastMessageFull(capturedConvId, {
                content: `Sorry, I encountered an error: ${error}. Please try again.`,
                isStreaming: false,
              });
              setStreaming(false);
            },
          },
          controller.signal,
        );
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          updateLastMessageFull(capturedConvId, {
            content: "Sorry, something went wrong. Please check your connection and try again.",
            isStreaming: false,
          });
          setStreaming(false);
        }
      }
    },
    [
      activeConversationId,
      chatMode,
      createConversation,
      addMessage,
      appendToLastMessage,
      updateLastMessageFull,
      setStreaming,
    ],
  );

  const handleClearChat = useCallback(() => {
    abortRef.current?.abort();
    if (activeConversationId) {
      deleteConversation(activeConversationId);
    }
  }, [activeConversationId, deleteConversation]);

  const handleSuggestionSelect = useCallback(
    (prompt: string) => {
      handleSend(prompt);
    },
    [handleSend],
  );

  // Listen for suggestion clicks from ChatMessage components
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (typeof detail === "string" && !isStreaming) {
        handleSend(detail);
      }
    };
    window.addEventListener("katha-suggestion-select", handler);
    return () => window.removeEventListener("katha-suggestion-select", handler);
  }, [handleSend, isStreaming]);

  return (
    <div className="flex h-screen bg-white">
      <Sidebar isOpen={sidebarOpen} onToggle={toggleSidebar} />

      {activeWorkspace === "knowledge-chat" ? (
        <div className="flex-1 flex flex-col min-w-0 relative">
          <ChatHeader
            conversationTitle={activeConversation?.title}
            sidebarOpen={sidebarOpen}
            onToggleSidebar={toggleSidebar}
            onClearChat={handleClearChat}
          />
          <ChatArea
            messages={activeConversation?.messages ?? []}
            isStreaming={isStreaming}
            onSuggestionSelect={handleSuggestionSelect}
          />
          <PromptInput onSend={handleSend} disabled={isStreaming} />
        </div>
      ) : (
        <ImageWorkspaceShell />
      )}
    </div>
  );
}
