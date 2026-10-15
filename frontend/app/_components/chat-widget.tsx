"use client";

/**
 * ChatWidget - the Data Chat Assistant (read-only, grounded).
 *
 * A persistent floating button that opens a chat panel. It answers questions
 * about the user's data (verdicts, churn, the portfolio) and how-to/concept
 * questions, grounded in the platform's own data and help content via
 * POST /api/v1/chat. It never changes any decision - the backend is read-only.
 *
 * Mounted once in the root layout so it survives route transitions and keeps a
 * local conversation thread. On a title page it passes that title as scope so
 * answers are about the title in context.
 */

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

import { api, ApiError } from "@/lib/api-client";
import type { ChatResponse, ChatTurn } from "@/lib/types";

type Message = ChatTurn & { sources?: string[]; followUps?: string[] };

/** How many trailing turns to send (mirrors the backend bound). */
const HISTORY_TURNS = 6;

/** Turn a raw source id (e.g. "title:abc", "doc:how-to-batch-slate") into a label. */
function sourceLabel(source: string): string {
  if (source === "portfolio") return "Portfolio summary";
  if (source.startsWith("projection:")) return "Valuation scorecard";
  if (source.startsWith("title:")) return "Title record";
  if (source.startsWith("doc:")) {
    const id = source.slice(4).replace(/^how-to-/, "").replace(/^concept-/, "");
    return "Help: " + id.replace(/-/g, " ");
  }
  return source;
}

/** Extract a title id from a /titles/{id} route, if present. */
function titleIdFromPath(pathname: string): string | null {
  const m = pathname.match(/\/titles\/([^/]+)/);
  return m ? m[1] : null;
}

/** Starter prompts shown on an empty thread; adapts to the current context. */
function starterPrompts(onTitlePage: boolean): string[] {
  if (onTitlePage) {
    return [
      "Why did this title get its verdict?",
      "Which guardrail checks passed or breached?",
      "Explain this title's churn mitigation",
      "What price would make this deal clear?",
    ];
  }
  return [
    "How many titles are GREENLIGHT?",
    "Why did The Ledger get NEGOTIATE HARD?",
    "What is CPVH?",
    "How do I upload a slate?",
  ];
}

export function ChatWidget() {
  const pathname = usePathname() ?? "";
  const titleId = titleIdFromPath(pathname);

  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFailed, setLastFailed] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Focus the input when the panel opens.
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Keep the transcript scrolled to the latest message.
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, pending]);

  const contextLabel = titleId ? "This title" : "Portfolio overview";

  async function sendText(raw: string) {
    const text = raw.trim();
    if (text === "" || pending) return;

    const history: ChatTurn[] = messages
      .slice(-HISTORY_TURNS)
      .map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setError(null);
    setLastFailed(null);
    setPending(true);

    try {
      const res: ChatResponse = await api.chat({
        message: text,
        title_id: titleId,
        history,
      });
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: res.answer,
          sources: res.sources,
          followUps: res.follow_ups ?? [],
        },
      ]);
      setLastFailed(null);
    } catch (err) {
      // Degrade gracefully: a timeout or an unavailable provider should never
      // dead-end. Show a plain-language message and let the user retry the
      // exact question they just asked.
      let msg = "The assistant could not be reached. Please try again.";
      if (err instanceof ApiError) {
        if (err.status === 503) {
          msg =
            "The assistant is busy right now (a slow model can take a while). " +
            "Try again, or switch to the fast built-in assistant.";
        } else {
          msg = err.envelope?.message ?? err.message;
        }
      }
      setError(msg);
      setLastFailed(text);
    } finally {
      setPending(false);
    }
  }

  function send() {
    void sendText(input);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <>
      {/* Floating action button */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={open ? "Close CineROI Copilot" : "Open CineROI Copilot"}
        title="CineROI Copilot"
        className="group fixed bottom-5 right-5 z-50 inline-flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-emerald-400 to-emerald-600 text-emerald-950 shadow-xl shadow-emerald-900/40 ring-1 ring-white/10 transition-all duration-200 hover:scale-105 hover:shadow-emerald-700/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300"
      >
        {open ? (
          <svg aria-hidden="true" viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        ) : (
          <svg aria-hidden="true" viewBox="0 0 24 24" className="h-7 w-7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5z" />
            <path d="M8.5 10.8l1.6 1.6 3.5-3.5" />
          </svg>
        )}
      </button>

      {/* Chat panel */}
      {open ? (
        <div
          role="dialog"
          aria-label="CineROI Copilot assistant"
          className="fixed bottom-24 right-4 z-50 flex h-[min(640px,calc(100vh-7rem))] w-[calc(100vw-2rem)] max-w-[420px] flex-col overflow-hidden rounded-2xl border border-slate-700/70 bg-slate-900/95 shadow-2xl shadow-black/50 backdrop-blur-sm duration-200 animate-in fade-in slide-in-from-bottom-4 sm:right-5"
        >
          {/* Header */}
          <div className="flex items-center justify-between gap-3 border-b border-slate-800 bg-gradient-to-r from-emerald-500/15 via-emerald-500/5 to-transparent px-4 py-3">
            <div className="flex items-center gap-3">
              <span className="relative inline-flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-emerald-400 to-emerald-600 text-emerald-950" aria-hidden="true">
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5z" />
                </svg>
              </span>
              <div className="flex flex-col">
                <span className="text-[15px] font-semibold leading-tight text-slate-50">CineROI Copilot</span>
                <span className="mt-1 inline-flex w-fit items-center gap-1.5 rounded-full bg-slate-800/80 px-2 py-0.5 text-[11px] font-medium text-slate-300">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_6px] shadow-emerald-400" aria-hidden="true" />
                  {contextLabel}
                  <span className="text-slate-500">&middot; read-only</span>
                </span>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close CineROI Copilot"
              className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-800 hover:text-slate-100"
            >
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>

          {/* Transcript */}
          <div
            ref={scrollRef}
            className="chat-scroll flex-1 space-y-4 overflow-y-auto px-4 py-4"
          >
            {messages.length === 0 ? (
              <div className="space-y-4">
                <div className="rounded-xl border border-slate-800 bg-slate-800/40 p-3.5">
                  <p className="text-sm leading-relaxed text-slate-300">
                    Hi, I&apos;m <span className="font-semibold text-slate-100">CineROI Copilot</span>.
                    I explain your titles&apos; verdicts, the portfolio, and the four
                    guardrails, and I can walk you through the portal. I only report what
                    the platform already computed &mdash; I never change a decision.
                  </p>
                </div>
                <p className="px-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  Suggested questions
                </p>
                <div className="flex flex-col gap-2">
                  {starterPrompts(titleId !== null).map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      onClick={() => void sendText(prompt)}
                      className="group flex w-full items-center justify-between gap-2 rounded-xl border border-slate-700/70 bg-slate-800/50 px-3.5 py-2.5 text-left text-sm text-slate-200 transition hover:border-emerald-500/60 hover:bg-emerald-500/10"
                    >
                      <span>{prompt}</span>
                      <span aria-hidden="true" className="text-slate-500 transition group-hover:translate-x-0.5 group-hover:text-emerald-400">&rarr;</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {messages.map((m, i) => {
              const isLast = i === messages.length - 1;
              const showFollowUps =
                m.role === "assistant" &&
                isLast &&
                !pending &&
                (m.followUps?.length ?? 0) > 0;
              const isUser = m.role === "user";
              return (
                <div key={i} className="space-y-2.5">
                  <div className={isUser ? "flex justify-end" : "flex items-start gap-2.5"}>
                    {!isUser ? (
                      <span className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400" aria-hidden="true">
                        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5z" />
                        </svg>
                      </span>
                    ) : null}
                    <div
                      className={
                        isUser
                          ? "max-w-[82%] rounded-2xl rounded-br-sm bg-emerald-500 px-3.5 py-2.5 text-sm leading-relaxed text-emerald-950 shadow-sm"
                          : "max-w-[88%] rounded-2xl rounded-tl-sm border border-slate-700/60 bg-slate-800/70 px-3.5 py-2.5 text-sm leading-relaxed text-slate-100 shadow-sm"
                      }
                    >
                      <p className="whitespace-pre-wrap">{m.content}</p>
                      {m.role === "assistant" && m.sources && m.sources.length > 0 ? (
                        <div className="mt-2.5 flex flex-wrap gap-1 border-t border-slate-700/50 pt-2">
                          {m.sources.map((src) => (
                            <span
                              key={src}
                              className="inline-flex items-center gap-1 rounded-md bg-slate-900/70 px-1.5 py-0.5 text-[10px] font-medium text-slate-400"
                            >
                              <svg viewBox="0 0 24 24" className="h-2.5 w-2.5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M4 4h12l4 4v12H4z"/></svg>
                              {sourceLabel(src)}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  </div>

                  {showFollowUps ? (
                    <div className="ml-9 flex flex-col gap-1.5" aria-label="Suggested follow-up questions">
                      {m.followUps!.map((q) => (
                        <button
                          key={q}
                          type="button"
                          onClick={() => void sendText(q)}
                          className="group inline-flex w-fit max-w-full items-center gap-1.5 rounded-full border border-emerald-600/40 bg-emerald-500/10 px-3 py-1.5 text-left text-xs text-emerald-200 transition hover:border-emerald-500 hover:bg-emerald-500/20"
                        >
                          <span aria-hidden="true" className="text-emerald-400 transition group-hover:translate-x-0.5">&rarr;</span>
                          <span className="truncate">{q}</span>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              );
            })}

            {pending ? (
              <div className="flex items-start gap-2.5">
                <span className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400" aria-hidden="true">
                  <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5z" />
                  </svg>
                </span>
                <div className="flex items-center gap-1.5 rounded-2xl rounded-tl-sm border border-slate-700/60 bg-slate-800/70 px-4 py-3">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-emerald-400 [animation-delay:-0.3s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-emerald-400 [animation-delay:-0.15s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-emerald-400" />
                </div>
              </div>
            ) : null}
          </div>

          <div aria-live="polite" className="sr-only">
            {pending ? "Assistant is thinking" : error ? error : ""}
          </div>

          {error ? (
            <div role="alert" className="mx-3 mb-1 flex items-center justify-between gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              <span>{error}</span>
              {lastFailed ? (
                <button
                  type="button"
                  onClick={() => void sendText(lastFailed)}
                  disabled={pending}
                  className="shrink-0 rounded-md border border-rose-500/40 px-2 py-0.5 font-semibold text-rose-100 transition hover:bg-rose-500/20 disabled:opacity-50"
                >
                  Retry
                </button>
              ) : null}
            </div>
          ) : null}

          {/* Composer */}
          <div className="flex items-end gap-2 border-t border-slate-800 bg-slate-900/80 px-3 py-3">
            <label htmlFor="chat-input" className="sr-only">
              Ask the assistant
            </label>
            <input
              id="chat-input"
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Ask about data or how-to..."
              className="flex-1 rounded-xl border border-slate-700 bg-slate-950/80 px-3.5 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 transition focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500/40"
            />
            <button
              type="button"
              onClick={send}
              disabled={pending || input.trim() === ""}
              aria-label="Send"
              className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-500 text-emerald-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
              </svg>
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
