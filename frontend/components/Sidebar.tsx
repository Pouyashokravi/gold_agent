"use client";

type SidebarProps = {
  tradeMode: boolean;
  onTradeModeChange: (v: boolean) => void;
  onNewChat: () => void;
};

export function Sidebar({ tradeMode, onTradeModeChange, onNewChat }: SidebarProps) {
  return (
    <aside className="flex flex-col w-[200px] sm:w-[260px] h-full bg-[var(--sidebar)] text-white shrink-0 border-r border-white/10">
      <div className="p-3 flex flex-col gap-2 h-full">
        <button
          onClick={onNewChat}
          className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg border border-white/15 hover:bg-[var(--sidebar-hover)] text-sm transition-colors"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 5v14M5 12h14" />
          </svg>
          New chat
        </button>

        <div className="flex-1" />

        <div className="border-t border-white/10 pt-3 space-y-3">
          <button
            type="button"
            role="switch"
            aria-checked={tradeMode}
            onClick={() => onTradeModeChange(!tradeMode)}
            className="flex items-center justify-between w-full px-3 py-2 rounded-lg hover:bg-[var(--sidebar-hover)] text-sm"
          >
            <span className="text-white/90">Trade analysis</span>
            <span className="toggle-track" data-on={tradeMode ? "true" : "false"} aria-hidden>
              <span className="toggle-thumb" />
            </span>
          </button>
          {tradeMode ? (
            <div className="px-3 text-[10px] uppercase tracking-wider text-emerald-400/80">
              Trader desk active
            </div>
          ) : (
            <div className="px-3 text-xs text-white/40">
              XAU/USD · Multi-agent research
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
