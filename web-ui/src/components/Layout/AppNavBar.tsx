import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Search, Settings, LogOut, User as UserIcon } from 'lucide-react';
import { motion, useReducedMotion } from 'motion/react';
import { useEffect, useRef, useState } from 'react';
import { apiClient } from '../../api/client';
import { signOut } from '../../lib/auth';
import { ViewSwitcher } from './ViewSwitcher';

interface MeInfo {
  username: string;
  email: string | null;
  workspace_path?: string | null;
}

export function AppNavBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const reduce = useReducedMotion();
  const [me, setMe] = useState<MeInfo | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiClient.me().then(u => {
      if (!cancelled) setMe(u as MeInfo | null);
    });
    return () => {
      cancelled = true;
    };
  }, [location.pathname]);

  // Close the menu on outside click / Escape
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    window.addEventListener('mousedown', onDown);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('mousedown', onDown);
      window.removeEventListener('keydown', onKey);
    };
  }, [menuOpen]);

  const handleSignOut = async () => {
    if (signingOut) return;
    setSigningOut(true);
    try {
      await signOut();
      setMe(null);
      setMenuOpen(false);
      navigate('/login', { replace: true });
    } finally {
      setSigningOut(false);
    }
  };

  const displayName = me?.username ?? '';
  const displayEmail = me?.email ?? '';
  const initial = (displayName || displayEmail || '?').slice(0, 1).toUpperCase();

  return (
    <motion.nav
      initial={reduce ? false : { opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      className="fixed top-0 left-0 right-0 h-14 bg-canvas/90 backdrop-blur-md border-b border-hairline-soft z-50"
    >
      <div className="h-full max-w-[1400px] mx-auto px-6 flex items-center justify-between">
        {/* Left: Brand + Nav */}
        <div className="flex items-center gap-8">
          <Link
            to="/chat"
            className="flex items-center gap-2 hover:opacity-70 transition-opacity"
          >
            <span className="text-[15px] font-[540] tracking-[-0.2px] text-ink">
              Atria
            </span>
          </Link>

          {/* Primary navigation: Chat ⇄ Dispatch (shared, consistent control) */}
          <ViewSwitcher />
        </div>

        {/* Right: Actions + User menu */}
        <div className="flex items-center gap-1">
          <button
            className="p-2 cursor-pointer text-ink/60 hover:text-ink hover:bg-surface-soft rounded-md transition-colors"
            title="Search"
            aria-label="Search"
          >
            <Search className="w-[18px] h-[18px]" strokeWidth={1.5} />
          </button>
          <button
            className="p-2 cursor-pointer text-ink/60 hover:text-ink hover:bg-surface-soft rounded-md transition-colors"
            title="Settings"
            aria-label="Settings"
          >
            <Settings className="w-[18px] h-[18px]" strokeWidth={1.5} />
          </button>

          {me && (
            <div className="relative ml-1" ref={menuRef}>
              <button
                type="button"
                onClick={() => setMenuOpen(v => !v)}
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
                <span className="text-[12px] font-mono max-w-[120px] truncate">
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
                    {signingOut ? 'Signing out…' : 'Sign out'}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </motion.nav>
  );
}
