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

type Message = ChatTurn & { sources?: string[] };

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

export function ChatWidget() {
  const pathname = usePathname() ?? "";
  const titleId = titleIdFromPath(pathname);

  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  async function send() {
    const text = input.trim();
    if (text === "" || pending) return;

    const history: ChatTurn[] = messages
      .slice(-HISTORY_TURNS)
      .map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setError(null);
    setPending(true);

    try {
      const res: ChatResponse = await api.chat({
        message: text,
        title_id: titleId,
        history,
      });
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: res.answer, sources: res.sources },
      ]);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.envelope?.message ?? err.message
          : "The assistant could not be reached. Please try again.";
      setError(msg);
    } finally {
      setPending(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
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
        aria-label={open ? "Close assistant" : "Open assistant"}
        className="fixed bottom-6 right-4 z-50 inline-flex h-12 w-12 items-center justify-center rounded-full bg-emerald-500 text-emerald-950 shadow-lg hover:bg-emerald-400 sm:right-6"
      >
        <span aria-hidden="true" className="text-lg font-bold">
          {open ? "\u00d7" : "\u2709"}
        </span>
      </button>

      {/* Chat panel */}
      {open ? (
        <div
          role="dialog"
          aria-label="CineROI assistant"
          className="fixed bottom-20 right-4 z-50 flex h-[520px] max-h-[80vh] w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-lg border border-slate-700 bg-slate-900 shadow-2xl sm:right-6 sm:w-96"
        >
          <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
            <div className="flex flex-col">
              <span className="text-sm font-semibold text-slate-100">CineROI Assistant</span>
              <span className="mt-0.5 inline-flex w-fit items-center rounded-full bg-slate-800 px-2 py-0.5 text-[11px] text-slate-300">
                Context: {contextLabel}
              </span>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close assistant"
              className="rounded-md px-2 py-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            >
              Close
            </button>
          </div>

          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
            {messages.length === 0 ? (
              <p className="text-sm text-slate-400">
                Ask about a title&apos;s verdict or churn, the portfolio, or how to
                use the portal (e.g. &quot;how do I upload a slate?&quot;). I only
                report what the platform shows - I never change a decision.
              </p>
            ) : null}

            {messages.map((m, i) => (
              <div
                key={i}
                className={
                  m.role === "user"
                    ? "ml-auto w-fit max-w-[85%] rounded-lg bg-emerald-500/15 px-3 py-2 text-sm text-emerald-100"
                    : "mr-auto w-fit max-w-[90%] rounded-lg bg-slate-800 px-3 py-2 text-sm text-slate-200"
                }
              >
                <p className="whitespace-pre-wrap">{m.content}</p>
                {m.role === "assistant" && m.sources && m.sources.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {m.sources.map((s) => (
                      <span
                        key={s}
                        className="inline-flex items-center rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[10px] text-slate-400"
                      >
                        {sourceLabel(s)}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}

            {pending ? (
              <div className="mr-auto flex items-center gap-2 rounded-lg bg-slate-800 px-3 py-2 text-sm text-slate-400">
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-emerald-500 border-t-transparent" />
                Thinking...
              </div>
            ) : null}
          </div>

          <div aria-live="polite" className="sr-only">
            {pending ? "Assistant is thinking" : error ? error : ""}
          </div>

          {error ? (
            <p role="alert" className="px-4 py-1 text-xs text-rose-400">
              {error}
            </p>
          ) : null}

          <div className="flex items-center gap-2 border-t border-slate-800 px-3 py-3">
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
              className="flex-1 rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-500 focus:border-emerald-500 focus:outline-none"
            />
            <button
              type="button"
              onClick={() => void send()}
              disabled={pending || input.trim() === ""}
              className="inline-flex items-center rounded-md bg-emerald-500 px-3 py-2 text-sm font-semibold text-emerald-950 hover:bg-emerald-400 disabled:opacity-50"
            >
              Send
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}