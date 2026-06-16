import { useEffect, useRef } from 'react';
import { wsClient } from '../../api/websocket';
import { apiClient } from '../../api/client';
import { useModulesStore, type BadgeSeverity } from '../../stores/modules';
import { useToastStore, type ToastVariant } from '../../stores/toast';
import type { WSMessage } from '../../types';

interface UseModuleBridgeArgs {
  moduleName: string;
  sessionId: string | null;
  iframeRef: React.RefObject<HTMLIFrameElement>;
  visible: boolean;
}

type InboundMessage =
  | { type: 'ready' }
  | { type: 'badge'; value: { count: number; severity: BadgeSeverity } | null }
  | { type: 'title'; text: string }
  | { type: 'toast'; message: string; severity?: ToastVariant }
  | {
      type: 'openBlock';
      block: string;
      props?: Record<string, unknown>;
    }
  | { type: 'openChat' }
  | {
      type: 'run';
      requestId: string;
      script: string;
      args?: string[];
      stdin?: string;
      timeout_ms?: number;
    };

const SEVERITY_TO_TOAST: Record<string, ToastVariant> = {
  info: 'info',
  success: 'success',
  warning: 'warning',
  danger: 'error',
  error: 'error',
};

/**
 * Bridge between the host React app and a module iframe.
 *
 * Listens for postMessage events from the iframe and proxies them to
 * stores / REST endpoints. Forwards lifecycle (`context`, `visibility`)
 * and module file change notifications (`change`) into the iframe.
 */
export function useModuleBridge({
  moduleName,
  sessionId,
  iframeRef,
  visible,
}: UseModuleBridgeArgs) {
  const readyRef = useRef(false);
  // Stash latest values in refs so the message handler stays referentially stable.
  const sessionIdRef = useRef(sessionId);
  const visibleRef = useRef(visible);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    visibleRef.current = visible;
  }, [visible]);

  // postMessage helper that targets the module iframe.
  const postToIframe = (msg: unknown) => {
    const win = iframeRef.current?.contentWindow;
    if (!win) return;
    // The iframe is loaded from a same-origin /api/modules/... endpoint, so '*' is
    // acceptable here; tighten if cross-origin hosting is introduced.
    win.postMessage(msg, '*');
  };

  // Listen for messages from the iframe.
  useEffect(() => {
    const handler = async (event: MessageEvent) => {
      const win = iframeRef.current?.contentWindow;
      if (!win || event.source !== win) return;

      const msg = event.data as InboundMessage | undefined;
      if (!msg || typeof msg !== 'object' || !('type' in msg)) return;

      switch (msg.type) {
        case 'ready': {
          readyRef.current = true;
          postToIframe({
            type: 'context',
            sessionId: sessionIdRef.current,
            module: moduleName,
          });
          postToIframe({ type: 'visibility', visible: visibleRef.current });
          break;
        }
        case 'badge': {
          useModulesStore.getState().setBadge(moduleName, msg.value ?? null);
          break;
        }
        case 'title': {
          window.dispatchEvent(
            new CustomEvent('atria:module:title', {
              detail: { module: moduleName, text: msg.text },
            }),
          );
          break;
        }
        case 'toast': {
          const variant = SEVERITY_TO_TOAST[msg.severity ?? 'info'] ?? 'info';
          useToastStore.getState().addToast(msg.message, variant);
          break;
        }
        case 'openBlock': {
          try {
            await apiClient.pushBlock(
              sessionIdRef.current,
              moduleName,
              msg.block,
              msg.props ?? {},
            );
            useModulesStore.getState().closeDashboard();
          } catch (err) {
            console.error('[module bridge] openBlock failed', err);
            useToastStore.getState().addToast(
              err instanceof Error ? err.message : 'Failed to open block',
              'error',
            );
          }
          break;
        }
        case 'openChat': {
          useModulesStore.getState().closeDashboard();
          break;
        }
        case 'run': {
          const { requestId, script, args, stdin, timeout_ms } = msg;
          try {
            const result = await apiClient.runModuleScript(moduleName, {
              script,
              args: args ?? [],
              stdin,
              timeout_ms,
            });
            if (!result.ok) {
              postToIframe({
                type: 'run:error',
                requestId,
                kind: `http_${result.status}`,
                message: result.message,
              });
              break;
            }
            const data = result.data;
            postToIframe({
              type: 'run:result',
              requestId,
              exit_code: data.exit_code,
              stdout: data.stdout,
              stderr: data.stderr,
              duration_ms: data.duration_ms,
            });
          } catch (err) {
            postToIframe({
              type: 'run:error',
              requestId,
              kind: 'network',
              message: err instanceof Error ? err.message : String(err),
            });
          }
          break;
        }
        default:
          break;
      }
    };

    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
    // moduleName + iframeRef are stable for the component's lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moduleName]);

  // Re-post context whenever sessionId changes (if iframe is ready).
  useEffect(() => {
    if (!readyRef.current) return;
    postToIframe({ type: 'context', sessionId, module: moduleName });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, moduleName]);

  // Re-post visibility whenever it flips.
  useEffect(() => {
    if (!readyRef.current) return;
    postToIframe({ type: 'visibility', visible });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  // Forward WS modules.changed events as 'change' messages to the iframe.
  useEffect(() => {
    const unsubscribe = wsClient.on('modules.changed', (payload: WSMessage) => {
      const data = (payload as { data?: { module?: string; paths?: string[] } }).data ?? {};
      const changed = data.module;
      if (changed && changed !== '*' && changed !== moduleName) return;
      postToIframe({ type: 'change', paths: data.paths ?? [] });
    });
    return () => {
      unsubscribe();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moduleName]);

  // Forward WS artifact.changed events into the iframe so the dashboard can
  // re-fetch CSVs / other artifacts edited from the artifact viewer.
  useEffect(() => {
    const unsubscribe = wsClient.on('artifact.changed', (payload: WSMessage) => {
      const d = payload as {
        scope?: string;
        conversation_id?: number;
        module?: string;
        path?: string;
      };
      // If this is a module-scope change, filter to our module.
      if (d.scope === 'module' && d.module && d.module !== moduleName) return;
      postToIframe({
        type: 'artifact:change',
        scope: d.scope,
        conversationId: d.conversation_id,
        module: d.module,
        path: d.path,
      });
    });
    return () => {
      unsubscribe();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moduleName]);
}
