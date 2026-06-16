import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, RotateCw } from 'lucide-react';
import { useChatStore } from '../../stores/chat';
import { useModulesStore } from '../../stores/modules';
import { useModuleBridge } from './useModuleBridge';

interface ModuleDashboardViewProps {
  moduleName: string;
}

/**
 * Renders a module's interactive dashboard.html inside a sandboxed iframe,
 * wrapped with a thin header that allows returning to chat or reloading.
 *
 * The actual host <-> iframe protocol is handled by `useModuleBridge`.
 */
export function ModuleDashboardView({ moduleName }: ModuleDashboardViewProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const currentSessionId = useChatStore((s) => s.currentSessionId);
  const closeDashboard = useModulesStore((s) => s.closeDashboard);
  const summary = useModulesStore((s) =>
    s.modulesWithDashboards.find((m) => m.name === moduleName) ?? null,
  );

  const manifestTitle = summary?.dashboard_title ?? `${moduleName} · dashboard`;
  const [title, setTitle] = useState<string>(manifestTitle);

  // Reset title when switching modules or when manifest changes.
  useEffect(() => {
    setTitle(manifestTitle);
  }, [manifestTitle]);

  // Listen for in-iframe title updates dispatched by the bridge.
  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ module: string; text: string }>).detail;
      if (!detail || detail.module !== moduleName) return;
      if (typeof detail.text === 'string' && detail.text.length > 0) {
        setTitle(detail.text);
      }
    };
    window.addEventListener('atria:module:title', handler as EventListener);
    return () =>
      window.removeEventListener('atria:module:title', handler as EventListener);
  }, [moduleName]);

  useModuleBridge({
    moduleName,
    sessionId: currentSessionId,
    iframeRef,
    visible: true,
  });

  const handleRefresh = () => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    // Reassigning src forces a fresh load while preserving the bridge listeners.
    iframe.src = iframe.src;
  };

  const iframeSrc = `/api/modules/${encodeURIComponent(moduleName)}/dashboard.html`;

  return (
    <div className="flex h-full w-full flex-col bg-bg-000">
      <header className="flex items-center gap-3 px-4 py-2 border-b border-border-300/15 bg-bg-100">
        <button
          type="button"
          onClick={closeDashboard}
          className="flex items-center gap-1.5 text-xs text-text-300 hover:text-text-100 transition-colors"
          aria-label="Back to chat"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          <span>Back</span>
        </button>

        <div className="h-3.5 w-px bg-border-300/20" aria-hidden />

        <h2
          className="text-xs font-medium text-text-200 truncate"
          title={title}
        >
          {title}
        </h2>

        <div className="ml-auto flex items-center">
          <button
            type="button"
            onClick={handleRefresh}
            className="p-1 rounded hover:bg-bg-200 text-text-400 hover:text-text-200 transition-colors"
            aria-label="Reload dashboard"
            title="Reload dashboard"
          >
            <RotateCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </header>

      <iframe
        ref={iframeRef}
        sandbox="allow-scripts allow-forms"
        src={iframeSrc}
        title={`${moduleName} dashboard`}
        className="flex-1 border-0 bg-bg-000"
      />
    </div>
  );
}

export default ModuleDashboardView;
