import { Command } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useEffect } from "react";
import { apiClient } from "../../api/client";
import { useChatStore } from "../../stores/chat";

function formatCost(cost: number): string {
  return cost < 0.01 ? `$${cost.toFixed(4)}` : `$${cost.toFixed(2)}`;
}

function getContextColor(pct: number): string {
  const remaining = 100 - pct;
  if (remaining < 25) return "bg-semantic-danger/10 text-semantic-danger border-semantic-danger/20";
  if (remaining < 50)
    return "bg-yellow-500/10 text-yellow-600 border-yellow-500/20";
  return "bg-emerald-500/10 text-emerald-700 border-emerald-500/20";
}

interface TopBarProps {
  onOpenCommandPalette?: () => void;
}

export function TopBar({ onOpenCommandPalette }: TopBarProps) {
  const reduce = useReducedMotion();
  const status = useChatStore((state) => state.status);
  const isConnected = useChatStore((state) => state.isConnected);
  const toggleSidebar = useChatStore((state) => state.toggleSidebar);
  // Load initial config on mount
  useEffect(() => {
    const loadStatus = async () => {
      try {
        const configData = await apiClient.getConfig();
        useChatStore.setState({
          thinkingLevel: configData.thinking_level || "Medium",
        });
        useChatStore.getState().setStatus({
          mode: configData.mode || "normal",
          autonomy_level: configData.autonomy_level || "Manual",
          thinking_level: configData.thinking_level || "Medium",
          model: configData.model,
          working_dir: configData.working_dir || "",
          git_branch: configData.git_branch,
        });
      } catch (_) {
        /* ignore */
      }
    };
    loadStatus();
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "b") {
        e.preventDefault();
        toggleSidebar();
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        onOpenCommandPalette?.();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [toggleSidebar, onOpenCommandPalette]);

  const getProjectName = (path: string) => {
    if (!path) return "";
    const parts = path.replace(/\/$/, "").split("/");
    return parts[parts.length - 1] || path;
  };

  const pillBase =
    "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium cursor-pointer transition-colors select-none hover-scale-pill";

  return (
    <motion.header
      initial={reduce ? false : { opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      className="h-12 flex-shrink-0 sticky top-0 z-40 flex items-center gap-3 px-4 bg-canvas/90 backdrop-blur-md border-b border-hairline-soft"
    >
      {/* ── Left: Sidebar toggle + Brand ── */}
      <div className="flex items-center gap-3 flex-shrink-0">
        {/* Wordmark */}
        <div className="flex items-baseline gap-2">
          <span className="text-[13px] font-[540] tracking-[-0.1px] text-ink">
            Atria
          </span>
          <span className="eyebrow-mono text-ink/40 hidden sm:inline">
            AI Assistant
          </span>
        </div>
      </div>

      {/* ── Spacer ── */}
      <div className="flex-1" />

      {/* ── Center-Right: Status Pills (minimal) ── */}
      {status && (
        <div className="flex items-center gap-2 flex-shrink-0">
          {/* Cost pill — only shown when agent has run */}
          {status.session_cost != null && status.session_cost > 0 && (
            <span
              className={`${pillBase} cursor-default bg-bg-200 text-text-300 border-border-300/30`}
              title={`Session cost: ${formatCost(status.session_cost)}`}
            >
              {formatCost(status.session_cost)}
            </span>
          )}

          {/* Context usage pill — only shown when available */}
          {status.context_usage_pct != null && (
            <span
              className={`${pillBase} cursor-default ${getContextColor(status.context_usage_pct)}`}
              title={`Context window: ${Math.round(status.context_usage_pct)}% used, ${Math.round(100 - status.context_usage_pct)}% remaining`}
            >
              Ctx: {Math.round(status.context_usage_pct)}%
            </span>
          )}

          {/* Command palette button */}
          <button
            onClick={onOpenCommandPalette}
            className={`${pillBase} bg-surface-soft text-ink/70 border-hairline-soft hover:bg-canvas hover:text-ink`}
            title="Command palette (Ctrl/Cmd+K)"
            aria-label="Open command palette"
          >
            <Command className="w-3 h-3" strokeWidth={1.5} />
          </button>

          {/* Connection pill */}
          <span
            className={`${pillBase} cursor-default ${
              isConnected
                ? "bg-semantic-success/10 text-semantic-success border-semantic-success/20"
                : "bg-surface-soft text-ink/50 border-hairline-soft"
            }`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${isConnected ? "bg-semantic-success" : "bg-ink/30"}`}
            />
            {isConnected ? "Connected" : "Offline"}
          </span>
        </div>
      )}

      {/* ── Far-Right: Project / Model ── */}
      {status && (
        <div className="items-center gap-2 text-[11px] text-ink/60 flex-shrink-0 ml-1 hidden md:flex">
          {status.working_dir && (
            <span className="truncate max-w-[160px]" title={status.working_dir}>
              {getProjectName(status.working_dir)}
              {status.git_branch && (
                <span className="text-ink/45">
                  <span className="text-ink/30"> / </span>
                  {status.git_branch}
                </span>
              )}
            </span>
          )}

          {status.working_dir && status.model && (
            <span className="text-ink/20">|</span>
          )}

          {status.model && (
            <span
              className="font-mono text-ink/55 truncate max-w-[140px]"
              title={status.model}
            >
              {status.model}
            </span>
          )}
        </div>
      )}
    </motion.header>
  );
}
