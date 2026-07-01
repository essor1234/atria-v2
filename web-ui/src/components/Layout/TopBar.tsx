import { Command, Settings, LogOut, Menu, User as UserIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { apiClient } from "../../api/client";
import { signOut } from "../../lib/auth";
import { useChatStore } from "../../stores/chat";
import { TenantSwitcher } from "../TenantSwitcher";
import { ViewSwitcher } from "./ViewSwitcher";

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

interface MeInfo {
  username: string;
  email: string | null;
  workspace_path?: string | null;
}

/**
 * TopBar — the single, persistent application chrome shared by every primary
 * surface (Chat ⇄ Dispatch). Rendered once by the layout shell so it never
 * unmounts on navigation: the brand, view switcher and user menu stay rock
 * steady while only the page body crossfades beneath it.
 *
 * Right-side controls are context-aware: chat-only status pills (cost, context,
 * connection, command palette) render only when a live session status exists,
 * while the tenant switcher, settings and user menu are always present so the
 * bar reads identically across surfaces.
 */
export function TopBar() {
  const navigate = useNavigate();
  const location = useLocation();
  const isChatSurface = location.pathname === "/chat";
  const status = useChatStore((state) => state.status);
  const isConnected = useChatStore((state) => state.isConnected);
  const toggleSidebar = useChatStore((state) => state.toggleSidebar);
  const openMobileSidebar = useChatStore((state) => state.openMobileSidebar);
  const openCommandPalette = useChatStore((state) => state.openCommandPalette);
  const openSettingsModal = useChatStore((state) => state.openSettingsModal);

  const [me, setMe] = useState<MeInfo | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

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

  // Identify the signed-in user for the account menu
  useEffect(() => {
    let cancelled = false;
    apiClient.me().then((u) => {
      if (!cancelled) setMe(u as MeInfo | null);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Close the account menu on outside click / Escape
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "b") {
        e.preventDefault();
        toggleSidebar();
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        openCommandPalette();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [toggleSidebar, openCommandPalette]);

  const handleSignOut = async () => {
    if (signingOut) return;
    setSigningOut(true);
    try {
      await signOut();
      setMe(null);
      setMenuOpen(false);
      navigate("/login", { replace: true });
    } finally {
      setSigningOut(false);
    }
  };

  const getProjectName = (path: string) => {
    if (!path) return "";
    const parts = path.replace(/\/$/, "").split("/");
    return parts[parts.length - 1] || path;
  };

  const displayName = me?.username ?? "";
  const displayEmail = me?.email ?? "";
  const initial = (displayName || displayEmail || "?").slice(0, 1).toUpperCase();

  const pillBase =
    "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium cursor-pointer transition-colors select-none hover-scale-pill";
  const iconBtn =
    "p-2 cursor-pointer text-ink/60 hover:text-ink hover:bg-surface-soft rounded-md transition-colors";

  return (
    <header className="h-14 flex-shrink-0 z-40 flex items-center gap-3 px-4 bg-canvas/90 backdrop-blur-md border-b border-hairline-soft">
      {/* ── Mobile: hamburger toggles the project drawer (chat surface only) ── */}
      {isChatSurface && (
        <button
          onClick={openMobileSidebar}
          className={`${iconBtn} md:hidden -ml-1`}
          title="Open menu"
          aria-label="Open navigation menu"
        >
          <Menu className="w-5 h-5" strokeWidth={1.5} />
        </button>
      )}

      {/* ── Left: Brand + primary view switcher ── */}
      <div className="flex items-center gap-4 flex-shrink-0">
        <div className="flex items-baseline gap-2">
          <span className="text-[15px] font-[540] tracking-[-0.2px] text-ink">
            Atria
          </span>
          <span className="eyebrow-mono text-ink/40 hidden lg:inline">
            AI Assistant
          </span>
        </div>

        {/* Primary navigation: Chat ⇄ Dispatch */}
        <ViewSwitcher />
      </div>

      {/* ── Spacer ── */}
      <div className="flex-1" />

      {/* ── Center-Right: chat-context status pills ── */}
      {status && (
        <div className="flex items-center gap-2 flex-shrink-0">
          {status.session_cost != null && status.session_cost > 0 && (
            <span
              className={`${pillBase} hidden sm:inline-flex cursor-default bg-bg-200 text-text-300 border-border-300/30`}
              title={`Session cost: ${formatCost(status.session_cost)}`}
            >
              {formatCost(status.session_cost)}
            </span>
          )}

          {status.context_usage_pct != null && (
            <span
              className={`${pillBase} hidden sm:inline-flex cursor-default ${getContextColor(status.context_usage_pct)}`}
              title={`Context window: ${Math.round(status.context_usage_pct)}% used, ${Math.round(100 - status.context_usage_pct)}% remaining`}
            >
              Ctx: {Math.round(status.context_usage_pct)}%
            </span>
          )}

          <button
            onClick={openCommandPalette}
            className={`${pillBase} bg-surface-soft text-ink/70 border-hairline-soft hover:bg-canvas hover:text-ink`}
            title="Command palette (Ctrl/Cmd+K)"
            aria-label="Open command palette"
          >
            <Command className="w-3 h-3" strokeWidth={1.5} />
          </button>

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
            <span className="hidden sm:inline">
              {isConnected ? "Connected" : "Offline"}
            </span>
          </span>
        </div>
      )}

      {/* ── Far-Right: Project / Model (chat-context) ── */}
      {status && (
        <div className="items-center gap-2 text-[11px] text-ink/60 flex-shrink-0 hidden xl:flex">
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

      {/* ── Persistent controls: tenant, settings, account (every surface) ── */}
      <div className="flex items-center gap-1 flex-shrink-0">
        <TenantSwitcher />

        <button
          onClick={openSettingsModal}
          className={iconBtn}
          title="Settings"
          aria-label="Settings"
        >
          <Settings className="w-[18px] h-[18px]" strokeWidth={1.5} />
        </button>

        {me && (
          <div className="relative ml-0.5" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              title={displayEmail || displayName}
              className="flex items-center gap-2 pl-1 pr-2 py-1 rounded-md cursor-pointer text-ink/80 hover:bg-surface-soft transition-colors"
            >
              <span
                className="w-6 h-6 rounded-full bg-ink text-inverse-ink text-[11px] font-[600] flex items-center justify-center"
                aria-hidden
              >
                {initial}
              </span>
              <span className="text-[12px] font-mono max-w-[120px] truncate hidden sm:inline">
                {displayName}
              </span>
            </button>

            {menuOpen && (
              <div
                role="menu"
                className="absolute right-0 mt-2 w-64 rounded-md border border-hairline-soft bg-canvas shadow-soft overflow-hidden z-50"
              >
                <div className="px-3 py-2.5 border-b border-hairline-soft">
                  <div className="flex items-center gap-2">
                    <UserIcon className="w-3.5 h-3.5 text-ink/60" strokeWidth={1.5} />
                    <span className="text-[12px] font-[540] text-ink truncate">
                      {displayName}
                    </span>
                  </div>
                  {displayEmail && (
                    <p
                      className="mt-0.5 text-[11px] text-ink/55 font-mono truncate"
                      title={displayEmail}
                    >
                      {displayEmail}
                    </p>
                  )}
                  {me.workspace_path && (
                    <p
                      className="mt-1 text-[10px] text-ink/45 font-mono truncate"
                      title={me.workspace_path}
                    >
                      {me.workspace_path}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={handleSignOut}
                  disabled={signingOut}
                  role="menuitem"
                  className="w-full flex items-center gap-2 px-3 py-2 text-[12px] text-ink/85 hover:bg-surface-soft cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <LogOut className="w-3.5 h-3.5" strokeWidth={1.5} />
                  {signingOut ? "Signing out…" : "Sign out"}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
