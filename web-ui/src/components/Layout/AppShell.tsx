import { useOutlet, useLocation } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { TopBar } from "./TopBar";
import { SettingsModal } from "../Settings/SettingsModal";
import { ToastContainer } from "../ui/Toast";
import { useChatStore } from "../../stores/chat";

/**
 * AppShell — the persistent application frame shared by every primary surface
 * (Chat ⇄ Dispatch). The TopBar is mounted once here and never unmounts on
 * navigation, so the chrome stays perfectly still; only the routed body below
 * crossfades. This is what makes view switching feel like swapping a panel
 * rather than reloading a page.
 */
export function AppShell() {
  const location = useLocation();
  const outlet = useOutlet();
  const reduce = useReducedMotion();
  const settingsModalOpen = useChatStore((s) => s.settingsModalOpen);
  const closeSettingsModal = useChatStore((s) => s.closeSettingsModal);

  return (
    <div className="h-[100dvh] flex flex-col bg-canvas overflow-hidden">
      <TopBar />

      <div className="flex-1 min-h-0 relative">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={location.pathname}
            initial={reduce ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={reduce ? undefined : { opacity: 0 }}
            transition={{
              duration: reduce ? 0 : 0.18,
              ease: [0.4, 0, 0.2, 1],
            }}
            className="absolute inset-0 flex flex-col min-h-0"
          >
            {outlet}
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Settings live in the shell so the shared TopBar gear works on every surface */}
      <SettingsModal isOpen={settingsModalOpen} onClose={closeSettingsModal} />
      <ToastContainer />
    </div>
  );
}
