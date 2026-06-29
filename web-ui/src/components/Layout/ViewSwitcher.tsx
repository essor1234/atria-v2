import { MessageSquare, Network } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { cn } from "../../lib/cn";
import { runningSolverCount, useSolverJobsStore } from "../../stores/solverJobs";

/**
 * ViewSwitcher — the single source of truth for switching between the two
 * primary surfaces of the app: the Chat window and the task-dispatch monitor
 * ("Dispatch", the work-division page at /divide).
 *
 * Best-practice notes:
 *  - One consistent control rendered identically on every surface, so the
 *    Chat <-> Dispatch switch lives in the same place no matter where you are.
 *  - Segmented control communicates "these are mutually-exclusive views" and
 *    surfaces the active view (aria-current + visual fill) instead of burying
 *    navigation in a lone icon pill.
 *  - Live badge on Dispatch shows running jobs, so while you're chatting you
 *    can see agents are working and jump straight to monitor them.
 *  - Keyboard accessible (real links, visible focus ring); icons carry text
 *    labels; the running count is announced via aria-label.
 */

interface ViewDef {
  to: string;
  label: string;
  Icon: typeof MessageSquare;
  /** Returns true when the current pathname belongs to this view. */
  isActive: (pathname: string) => boolean;
}

const VIEWS: ViewDef[] = [
  {
    to: "/chat",
    label: "Chat",
    Icon: MessageSquare,
    isActive: (p) => p === "/" || p.startsWith("/chat"),
  },
  {
    to: "/dispatch",
    label: "Dispatch",
    Icon: Network,
    isActive: (p) =>
      p.startsWith("/dispatch") || p.startsWith("/divide") || p.startsWith("/parallel"),
  },
];

export function ViewSwitcher({ className }: { className?: string }) {
  const location = useLocation();
  const runningJobs = useSolverJobsStore(runningSolverCount);

  return (
    <nav
      aria-label="Primary view"
      className={cn(
        "inline-flex items-center gap-0.5 p-0.5 rounded-lg",
        "bg-surface-soft border border-hairline-soft",
        className,
      )}
    >
      {VIEWS.map(({ to, label, Icon, isActive }) => {
        const active = isActive(location.pathname);
        const isDispatch = to === "/dispatch";
        const showBadge = isDispatch && runningJobs > 0;
        return (
          <Link
            key={to}
            to={to}
            aria-current={active ? "page" : undefined}
            aria-label={
              showBadge ? `${label}, ${runningJobs} running` : label
            }
            className={cn(
              "relative inline-flex items-center gap-1.5 h-8 px-3 rounded-md",
              "text-[13px] font-[480] tracking-[-0.1px] select-none cursor-pointer",
              "transition-colors duration-200",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink/30 focus-visible:ring-offset-1 focus-visible:ring-offset-canvas",
              active
                ? "bg-canvas text-ink shadow-soft border border-hairline-soft"
                : "text-ink/60 hover:text-ink hover:bg-canvas/60 border border-transparent",
            )}
          >
            <Icon className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
            <span>{label}</span>
            {showBadge && (
              <span
                className="ml-0.5 inline-flex items-center gap-1 pl-1.5 pr-1.5 h-4 rounded-full bg-amber-400/15 text-amber-500 text-[10px] font-mono font-[600] leading-none"
                aria-hidden="true"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse-dot" />
                {runningJobs}
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}
