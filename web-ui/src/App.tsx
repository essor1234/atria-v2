import { BrowserRouter as Router, Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, MotionConfig, useReducedMotion } from 'motion/react';
import { ChatPage } from './pages/ChatPage';
import { DispatchPage } from './pages/DispatchPage';
import './stores/solverJobs';
import { LoginPage } from './pages/LoginPage';
import { TenantsPage } from './pages/admin/TenantsPage';
import { TenantUsersPage } from './pages/admin/TenantUsersPage';
import { apiClient } from './api/client';
import { resetAllStores } from './lib/auth';

type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

// Tracks the last authenticated identity across guard mounts so we can
// detect "different account logged in this tab" and wipe the previous
// user's in-memory stores before showing the new user's pages.
const lastUserKey = { current: null as string | null };

function AuthGuard({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const navigate = useNavigate();
  const myCallId = useRef(0);

  useEffect(() => {
    const callId = ++myCallId.current;
    apiClient.me().then(user => {
      if (callId !== myCallId.current) return;
      if (user) {
        // Use email when available (stable), fall back to username.
        const key = (user as { email?: string | null }).email || user.username;
        if (lastUserKey.current && lastUserKey.current !== key) {
          resetAllStores();
        }
        lastUserKey.current = key;
        setStatus('authenticated');
      } else {
        if (lastUserKey.current !== null) {
          resetAllStores();
          lastUserKey.current = null;
        }
        setStatus('unauthenticated');
        navigate('/login', { replace: true });
      }
    });
  }, [navigate]);

  if (status === 'loading') return null;
  if (status === 'unauthenticated') return null;
  return <>{children}</>;
}

/**
 * Editorial route fade — soft opacity swap, no slide. Matches DESIGN.md
 * shadow-light rhythm; the route change feels like flipping a printed page,
 * not a SaaS panel transition.
 */
function RouteFade({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const reduce = useReducedMotion();
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={location.pathname}
        initial={reduce ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={reduce ? undefined : { opacity: 0 }}
        transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
        className="h-full"
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

function AppRoutes() {
  return (
    <RouteFade>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/chat" element={<AuthGuard><ChatPage /></AuthGuard>} />
        <Route path="/dispatch" element={<AuthGuard><DispatchPage /></AuthGuard>} />
        {/* Old split routes now fold into the unified Dispatch view */}
        <Route path="/divide" element={<Navigate to="/dispatch" replace />} />
        <Route path="/parallel" element={<Navigate to="/dispatch" replace />} />
        <Route path="/admin/tenants" element={<AuthGuard><TenantsPage /></AuthGuard>} />
        <Route path="/admin/tenants/:slug/users" element={<AuthGuard><TenantUsersPage /></AuthGuard>} />
        <Route path="/" element={<Navigate to="/chat" replace />} />
        {/* Any unknown / removed route (e.g. the old /codewiki) falls back to chat */}
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Routes>
    </RouteFade>
  );
}

function App() {
  return (
    <MotionConfig reducedMotion="always">
      <Router>
        <AppRoutes />
      </Router>
    </MotionConfig>
  );
}

export default App;
