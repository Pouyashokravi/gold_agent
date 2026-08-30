"use client";

type Props = {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
};

export function ChatMessage({ role, content, streaming }: Props) {
  if (role === "user") {
    return (
      <div className="flex justify-end px-4 py-3">
        <div className="max-w-[85%] md:max-w-[70%] bg-[var(--user-bubble)] rounded-3xl px-4 py-2.5 text-[15px] leading-relaxed text-[var(--text)]">
          {content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-4 px-4 py-3 max-w-3xl mx-auto w-full">
      <div className="w-8 h-8 rounded-full bg-[#2f2f2f] border border-[#444444] flex items-center justify-center shrink-0 mt-0.5">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ececec" strokeWidth="1.8">
          <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
        </svg>
      </div>
      <div className="flex-1 min-w-0 pt-0.5">
        <p className="text-xs font-medium text-[var(--text-secondary)] mb-1">Gold Agent</p>
        <div className="markdown-body text-[15px] text-[var(--text)]">
          {content}
          {streaming && (
            <span className="inline-block w-2 h-4 ml-0.5 bg-[var(--text)] animate-pulse align-middle" />
          )}
        </div>
      </div>
    </div>
  );
}
