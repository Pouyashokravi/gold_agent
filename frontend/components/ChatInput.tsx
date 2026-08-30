"use client";

type Props = {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  disabled: boolean;
};

export function ChatInput({ value, onChange, onSend, disabled }: Props) {
  return (
    <div className="shrink-0 bg-[var(--main)]">
      <div className="max-w-3xl mx-auto px-4 py-4">
        <div className="relative flex items-end rounded-[28px] border border-[var(--border)] bg-[var(--surface)] focus-within:border-[#666666] transition-colors">
          <textarea
            rows={1}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSend();
              }
            }}
            placeholder="Ask about XAU/USD gold..."
            disabled={disabled}
            className="flex-1 resize-none bg-transparent px-4 py-3.5 text-[15px] text-[var(--text)] placeholder:text-[var(--text-secondary)] focus:outline-none max-h-[200px] disabled:opacity-50"
          />
          <button
            onClick={onSend}
            disabled={disabled || !value.trim()}
            className="m-2 p-2 rounded-full bg-[#ececec] text-[#171717] disabled:bg-[#3a3a3a] disabled:text-[#6a6a6a] hover:bg-white transition-colors"
            aria-label="Send"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        </div>
        <p className="text-center text-xs text-[var(--text-secondary)] mt-2">
          AI market analysis only — not financial advice
        </p>
      </div>
    </div>
  );
}
