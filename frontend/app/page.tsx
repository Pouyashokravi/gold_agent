"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AgentStatus } from "@/components/AgentStatus";
import { ChatInput } from "@/components/ChatInput";
import { ChatMessage } from "@/components/ChatMessage";
import { ResultCard } from "@/components/ResultCard";
import { Sidebar } from "@/components/Sidebar";
import { WelcomeScreen } from "@/components/WelcomeScreen";
import { TraderAnalysisPanel } from "@/components/TraderAnalysisPanel";
import { TraderChart } from "@/components/TraderChart";
import { TraderTicker } from "@/components/TraderTicker";
import { analyzeStream, createConversation } from "@/lib/api";
import type { ChartInterval, ChatMessage as ChatMsg, StreamEvent, SynthesisData } from "@/types";

export default function Home() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [tradeMode, setTradeMode] = useState(false);
  const [conversationId, setConversationId] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [activeStep, setActiveStep] = useState("");
  const [completed, setCompleted] = useState<Set<string>>(new Set());
  const [synthesis, setSynthesis] = useState<SynthesisData | null>(null);
  const [enabledAgents, setEnabledAgents] = useState<Record<string, boolean>>({
    news: true,
    fundamental: true,
    technical: true,
  });
  const [statusMessage, setStatusMessage] = useState("");
  const [chatMode, setChatMode] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, streamText, synthesis, streaming]);

  const initConversation = useCallback(async () => {
    const id = await createConversation();
    localStorage.setItem("conversation_id", id);
    setConversationId(id);
    return id;
  }, []);

  useEffect(() => {
    const init = async () => {
      try {
        const stored = localStorage.getItem("conversation_id");
        if (stored) {
          setConversationId(stored);
          return;
        }
        await initConversation();
      } catch (e) {
        console.error(e);
      }
    };
    init();
  }, [initConversation]);

  const markStep = useCallback((type: string) => {
    const startMap: Record<string, string> = {
      understanding_started: "understanding",
      planning_started: "planning",
      news_agent_started: "news_agent",
      fundamental_agent_started: "fundamental_agent",
      technical_agent_started: "technical_agent",
      synthesis_started: "synthesis",
      answer_started: "answer",
    };
    const doneMap: Record<string, string> = {
      understanding_completed: "understanding",
      planning_completed: "planning",
      news_agent_completed: "news_agent",
      fundamental_agent_completed: "fundamental_agent",
      technical_agent_completed: "technical_agent",
      synthesis_completed: "synthesis",
      answer_completed: "answer",
    };
    if (startMap[type]) setActiveStep(startMap[type]);
    if (doneMap[type]) setCompleted((prev) => new Set([...prev, doneMap[type]]));
  }, []);

  const send = async (text?: string) => {
    const query = (text ?? input).trim();
    if (!query || streaming) return;
    if (!conversationId) return;

    setInput("");
    setMessages((m) => [...m, { role: "user", content: query }]);
    setStreaming(true);
    setStreamText("");
    setSynthesis(null);
    setCompleted(new Set());
    setChatMode(false);
    setActiveStep("understanding");
    setStatusMessage("Understanding your query...");

    abortRef.current = new AbortController();
    let answer = "";

    try {
      await analyzeStream(query, conversationId, tradeMode, (event: StreamEvent) => {
        if (event.type === "chat_response") {
          setChatMode(true);
          setActiveStep("");
          setStatusMessage("");
          return;
        }
        markStep(event.type);
        if (event.message) setStatusMessage(event.message);
        if (event.type === "answer_delta" && event.data?.delta) {
          answer += event.data.delta as string;
          setStreamText(answer);
        }
        if (event.type === "check_completed" && event.data?.agents) {
          setEnabledAgents(event.data.agents as Record<string, boolean>);
        }
        if (event.type === "synthesis_completed" && event.data) {
          setSynthesis(event.data as SynthesisData);
        }
        if (event.type === "answer_completed" && event.data?.answer) {
          answer = event.data.answer as string;
        }
        if (event.type === "error") {
          answer += `\n\n⚠ ${event.message}`;
          setStreamText(answer);
        }
      }, abortRef.current.signal);

      if (answer) setMessages((m) => [...m, { role: "assistant", content: answer }]);
      setStreamText("");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Request failed.";
      setMessages((m) => [...m, { role: "assistant", content: msg }]);
    } finally {
      setStreaming(false);
    }
  };

  const newChat = async () => {
    setMessages([]);
    setSynthesis(null);
    setStreamText("");
    setCompleted(new Set());
    try {
      await initConversation();
    } catch (e) {
      console.error(e);
    }
  };

  const hasMessages = messages.length > 0 || streaming;

  return (
    <div className="flex h-screen w-full overflow-hidden bg-[var(--main)]">
      <Sidebar
        tradeMode={tradeMode}
        onTradeModeChange={setTradeMode}
        onNewChat={newChat}
      />

      <div className="flex flex-1 min-w-0 h-full flex-col lg:flex-row">
        <div className="flex flex-col flex-1 min-w-0 min-h-0 order-2 lg:order-1 bg-[var(--main)]">
          <header className="flex items-center gap-3 px-4 py-3 border-b border-[var(--border)] shrink-0">
            <h1 className="text-[15px] font-semibold text-[var(--text)]">
              {tradeMode ? "Gold Trader Desk" : "Gold Research Agent"}
            </h1>
            <span className="text-xs text-[var(--text-secondary)] hidden sm:inline">XAU/USD</span>
            {tradeMode ? (
              <span className="ml-auto text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full border border-[var(--border)] text-[var(--text-secondary)]">
                Trader
              </span>
            ) : null}
          </header>

          <div className="flex-1 overflow-y-auto min-h-0">
            {!hasMessages ? (
              <WelcomeScreen
                tradeMode={tradeMode}
                onSuggestion={(s) => {
                  setInput(s);
                  send(s);
                }}
              />
            ) : (
              <div className="py-4">
                {messages.map((m, i) => (
                  <ChatMessage key={i} role={m.role} content={m.content} />
                ))}
                {streaming && streamText && (
                  <ChatMessage role="assistant" content={streamText} streaming={!streamText.startsWith("\n\n⚠")} />
                )}
                {streaming && !streamText && (
                  <div className="flex gap-4 px-4 py-3 max-w-3xl mx-auto w-full">
                    <div className="w-8 h-8 rounded-full bg-[#2f2f2f] border border-[#444444] shrink-0" />
                    <div className="flex gap-1 items-center pt-2">
                      <span className="typing-dot w-2 h-2 rounded-full bg-[var(--text-secondary)]" />
                      <span className="typing-dot w-2 h-2 rounded-full bg-[var(--text-secondary)]" />
                      <span className="typing-dot w-2 h-2 rounded-full bg-[var(--text-secondary)]" />
                    </div>
                  </div>
                )}
                <ResultCard synthesis={synthesis} />
                <div ref={bottomRef} />
              </div>
            )}
          </div>

          <AgentStatus
            activeStep={activeStep}
            completed={completed}
            visible={streaming && !chatMode}
            statusMessage={statusMessage}
            enabledAgents={enabledAgents}
          />
          <ChatInput value={input} onChange={setInput} onSend={() => send()} disabled={streaming || !conversationId} />
        </div>

        {tradeMode ? (
          <aside className="order-1 lg:order-2 w-full lg:w-[420px] xl:w-[440px] shrink-0 border-b lg:border-b-0 lg:border-l border-[var(--border)] flex flex-col min-h-0 h-[42%] lg:h-full bg-[#171717]">
            <TraderTicker />
            <div className="flex-1 min-h-0 p-3 flex flex-col gap-3 overflow-hidden">
              <div className="flex-1 min-h-[180px]">
                <TraderChart
                  annotations={synthesis?.chart_annotations}
                  defaultInterval={
                    (synthesis?.chart_annotations?.default_interval === "1h"
                      ? "1H"
                      : "1H") as ChartInterval
                  }
                />
              </div>
              <div className="shrink-0 max-h-[46%] overflow-y-auto">
                <TraderAnalysisPanel synthesis={synthesis} />
              </div>
            </div>
          </aside>
        ) : null}
      </div>
    </div>
  );
}
