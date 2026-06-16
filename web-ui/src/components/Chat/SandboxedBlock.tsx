import { memo, useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { useChatStore } from '../../stores/chat';

const THEME_VAR_NAMES = [
  '--background',
  '--foreground',
  '--primary',
  '--primary-foreground',
  '--secondary',
  '--secondary-foreground',
  '--muted',
  '--muted-foreground',
  '--accent',
  '--accent-foreground',
  '--destructive',
  '--destructive-foreground',
  '--border',
  '--input',
  '--ring',
  '--card',
  '--card-foreground',
  '--popover',
  '--popover-foreground',
];

function readThemeTokens(): { mode: string; tokens: Record<string, string> } {
  const root = document.documentElement;
  const styles = getComputedStyle(root);
  const tokens: Record<string, string> = {};
  for (const name of THEME_VAR_NAMES) {
    const value = styles.getPropertyValue(name).trim();
    if (value) tokens[name] = value;
  }
  const mode = root.classList.contains('dark') ? 'dark' : 'light';
  return { mode, tokens };
}

export interface SandboxedBlockProps {
  blockId: string;
  src: string;
  props: Record<string, any>;
  height?: number | 'auto';
  title?: string;
}

const MIN_HEIGHT = 40;

export const SandboxedBlock = memo(function SandboxedBlock({
  blockId,
  src,
  props,
  height,
  title,
}: SandboxedBlockProps) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const readyRef = useRef(false);
  const [iframeHeight, setIframeHeight] = useState<number | undefined>(() =>
    typeof height === 'number' ? Math.max(height, MIN_HEIGHT) : undefined,
  );
  const propsRef = useRef(props);
  propsRef.current = props;

  const iframeSrc = useMemo(() => {
    const sep = src.includes('?') ? '&' : '?';
    return `${src}${sep}block_id=${encodeURIComponent(blockId)}`;
  }, [src, blockId]);

  const post = useCallback((message: any) => {
    const win = iframeRef.current?.contentWindow;
    if (!win) return;
    try {
      win.postMessage(message, '*');
    } catch (err) {
      console.warn('[SandboxedBlock] postMessage failed', err);
    }
  }, []);

  const sendInit = useCallback(() => {
    const theme = readThemeTokens();
    post({
      v: 1,
      block_id: blockId,
      type: 'init',
      payload: {
        props: propsRef.current,
        theme,
        readonly: true,
      },
    });
  }, [blockId, post]);

  // Inbound messages from iframe — only honor `ready` and `resize`.
  // All outbound channels (events, RPC) are intentionally dropped: blocks
  // are view-only and must not talk back to the server from the chat surface.
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      if (!iframeRef.current) return;
      if (event.source !== iframeRef.current.contentWindow) return;
      const data = event.data;
      if (!data || typeof data !== 'object') return;
      const type = data.type;
      if (type === 'ready') {
        readyRef.current = true;
        sendInit();
        return;
      }
      if (type === 'resize') {
        const h = data.payload?.height ?? data.height;
        const raw = h === 'auto' ? data.payload?.measured ?? data.payload?.value : h;
        const num = typeof raw === 'number' ? raw : Number(raw);
        if (Number.isFinite(num)) {
          setIframeHeight(Math.max(num, MIN_HEIGHT));
        }
        return;
      }
      // The one allowed outbound channel: inject free-text user message
      // into the chat. Routes through the normal send path so the agent
      // sees it exactly like a typed prompt.
      if (type === 'chat') {
        const text = typeof data.text === 'string' ? data.text.trim() : '';
        if (text) useChatStore.getState().sendMessage(text);
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [sendInit]);

  // Push prop changes (one-way: server → block).
  useEffect(() => {
    if (!readyRef.current) return;
    post({ type: 'props', payload: { props } });
  }, [props, post]);

  // Push explicit height override from server.
  useEffect(() => {
    if (typeof height === 'number') {
      setIframeHeight(Math.max(height, MIN_HEIGHT));
    }
  }, [height]);

  // Re-emit theme on theme/class changes.
  useEffect(() => {
    const root = document.documentElement;
    const observer = new MutationObserver(() => {
      if (!readyRef.current) return;
      post({ type: 'theme', payload: { theme: readThemeTokens() } });
    });
    observer.observe(root, { attributes: true, attributeFilter: ['class', 'style', 'data-theme'] });
    return () => observer.disconnect();
  }, [post]);

  return (
    <div className="max-w-4.5xl mx-auto px-4 md:px-8 py-3">
      <div className="rounded-lg border border-border bg-card shadow-sm overflow-hidden">
        {title ? (
          <div className="px-3 py-2 border-b border-border bg-muted/40 text-sm font-medium text-foreground">
            {title}
          </div>
        ) : null}
        <iframe
          ref={iframeRef}
          src={iframeSrc}
          sandbox="allow-scripts allow-forms"
          title={title || `block-${blockId}`}
          className="w-full block bg-background"
          style={{ height: iframeHeight, border: 0, display: 'block' }}
        />
      </div>
    </div>
  );
});

export default SandboxedBlock;
