import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { RefreshCw, ExternalLink, Code2, Eye } from 'lucide-react';
import { apiClient } from '../../../api/client';
import { fsScopeKey, type FsScope } from '../../../types';

const MonacoViewer = lazy(() =>
  import('./MonacoViewer').then(m => ({ default: m.MonacoViewer })),
);

interface Props {
  scope: FsScope;
  path: string;
  /** When true and scope is module, the Source tab edits + saves via Monaco. */
  editable?: boolean;
}

const SHIM_TAG = '__atria_html_viewer_shim__';

/** Shim script injected into the iframe. Intercepts fetch + XHR for same-origin
 *  or relative URLs and proxies them through the parent window via postMessage.
 *  The parent fulfills the request via the authenticated FS endpoint.
 */
function buildShim(htmlDir: string): string {
  return `<script id="${SHIM_TAG}">(function(){
    var BASE_DIR = ${JSON.stringify(htmlDir)};
    var PENDING = new Map();
    var SEQ = 0;
    function nextId(){ return 'r' + (++SEQ) + '-' + Date.now(); }
    function normalize(url){
      var u = String(url || '');
      if (!u) return null;
      // external — pass through
      if (/^(https?:)?\\/\\//.test(u) && !/^https?:\\/\\/(localhost|127\\.0\\.0\\.1|0\\.0\\.0\\.0)/.test(u)) return null;
      if (/^(data:|blob:|javascript:|about:)/.test(u)) return null;
      // strip scheme+host if present (same-origin variants like http://localhost:8080/foo.csv)
      u = u.replace(/^https?:\\/\\/[^/]+/, '');
      // root-relative '/foo.csv' → treat as sibling of the HTML
      // relative './foo.csv' or 'foo.csv' → sibling too
      var rel = u.replace(/^\\/+/, '').replace(/^\\.\\//, '');
      var base = BASE_DIR ? (BASE_DIR + '/') : '';
      return (base + rel).replace(/\\/+/g, '/');
    }
    window.addEventListener('message', function(ev){
      var d = ev.data || {};
      if (!d.__atria_reply) return;
      var entry = PENDING.get(d.__atria_reply);
      if (!entry) return;
      PENDING.delete(d.__atria_reply);
      entry(d);
    });
    function request(method, url, body){
      return new Promise(function(resolve){
        var id = nextId();
        PENDING.set(id, resolve);
        parent.postMessage({ __atria_request: id, method: method, url: url, body: body }, '*');
      });
    }
    var origFetch = window.fetch;
    window.fetch = function(input, init){
      var url = typeof input === 'string' ? input : (input && input.url) || '';
      var fs = normalize(url);
      if (!fs) return origFetch.apply(this, arguments);
      var method = (init && init.method) || 'GET';
      return request(method, fs).then(function(d){
        if (d.error) return Promise.reject(new Error(d.error));
        var body = d.body == null ? '' : d.body;
        return new Response(body, { status: 200, statusText: 'OK',
          headers: { 'Content-Type': d.contentType || 'application/octet-stream' } });
      });
    };
    var OrigXHR = window.XMLHttpRequest;
    function ShimXHR(){
      var x = new OrigXHR();
      var origOpen = x.open.bind(x);
      var origSend = x.send.bind(x);
      var capturedUrl = null;
      var capturedMethod = 'GET';
      var fsTarget = null;
      x.open = function(method, url){
        capturedMethod = method;
        capturedUrl = url;
        fsTarget = normalize(url);
        if (!fsTarget) return origOpen.apply(null, arguments);
        // delay calling open until send (we'll fake the response)
      };
      x.send = function(body){
        if (!fsTarget) return origSend.apply(null, arguments);
        request(capturedMethod, fsTarget, body || null).then(function(d){
          // Fake an XHR completion. Use Object.defineProperty because some props are read-only.
          function set(k, v){ try { Object.defineProperty(x, k, { configurable: true, get: function(){ return v; } }); } catch(_){} }
          if (d.error) {
            set('status', 0);
            set('readyState', 4);
            if (typeof x.onerror === 'function') x.onerror(new Event('error'));
            if (typeof x.onreadystatechange === 'function') x.onreadystatechange();
            return;
          }
          var responseText = d.body || '';
          set('status', 200);
          set('statusText', 'OK');
          set('readyState', 4);
          set('responseText', responseText);
          set('response', responseText);
          set('responseURL', capturedUrl);
          if (typeof x.onload === 'function') x.onload(new Event('load'));
          if (typeof x.onreadystatechange === 'function') x.onreadystatechange();
          if (typeof x.onloadend === 'function') x.onloadend(new Event('loadend'));
        });
      };
      return x;
    }
    ShimXHR.prototype = OrigXHR.prototype;
    window.XMLHttpRequest = ShimXHR;
  })();</` + `script>`;
}

function injectShim(html: string, htmlDir: string): string {
  const shim = buildShim(htmlDir);
  const headMatch = html.match(/<head[^>]*>/i);
  if (headMatch) {
    const idx = headMatch.index! + headMatch[0].length;
    return html.slice(0, idx) + shim + html.slice(idx);
  }
  // No <head> — prepend
  return shim + html;
}

function dirname(p: string): string {
  const i = p.lastIndexOf('/');
  return i === -1 ? '' : p.slice(0, i);
}

export function HtmlViewer({ scope, path, editable = false }: Props) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [mode, setMode] = useState<'preview' | 'source'>('preview');
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const scopeKey = useMemo(() => fsScopeKey(scope), [scope]);
  const canEdit = editable && scope.kind === 'module';

  useEffect(() => {
    let cancelled = false;
    setText(null);
    setError(null);
    apiClient
      .readFsText(scope, path)
      .then(t => {
        if (!cancelled) setText(t);
      })
      .catch(e => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [scopeKey, path, reloadKey]);

  // Listen for shim requests from the iframe and fulfill via FS endpoint.
  useEffect(() => {
    const handler = async (event: MessageEvent) => {
      const d = event.data;
      if (!d || !d.__atria_request) return;
      const iframeWin = iframeRef.current?.contentWindow;
      if (!iframeWin || event.source !== iframeWin) return;
      const reply = (payload: Record<string, unknown>) => {
        iframeWin.postMessage({ __atria_reply: d.__atria_request, ...payload }, '*');
      };
      try {
        const blob = await apiClient.readFsBlob(scope, d.url);
        const contentType = blob.type || 'application/octet-stream';
        const isText = /^text\/|json|xml|csv|javascript|svg/.test(contentType);
        const body = isText ? await blob.text() : await blob.arrayBuffer();
        reply({ body, contentType });
      } catch (err) {
        reply({ error: String(err) });
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [scopeKey]);

  const srcDoc = useMemo(() => {
    if (text == null) return '';
    return injectShim(text, dirname(path));
  }, [text, path]);

  if (error) {
    return (
      <div className="p-4 text-xs font-mono text-block-coral">
        Failed to load file: {error}
      </div>
    );
  }
  if (text === null) {
    return <div className="p-4 text-xs font-mono text-ink/45">Loading…</div>;
  }

  const externalUrl = apiClient.readFsUrl(scope, path);

  const segBtn = (active: boolean) =>
    `inline-flex items-center gap-1 px-2 py-0.5 text-[12px] font-mono rounded cursor-pointer transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-sky-400/60 ${
      active ? 'bg-ink/10 text-ink' : 'text-ink/55 hover:bg-surface-soft hover:text-ink/80'
    }`;

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-1 px-2 py-1 border-b border-hairline-soft">
        {canEdit && (
          <div role="tablist" aria-label="View mode" className="flex items-center gap-0.5 bg-ink/5 rounded p-0.5">
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'preview'}
              onClick={() => setMode('preview')}
              title="Preview rendered HTML"
              className={segBtn(mode === 'preview')}
            >
              <Eye className="w-3 h-3" />
              Preview
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'source'}
              onClick={() => setMode('source')}
              title="Edit HTML source"
              className={segBtn(mode === 'source')}
            >
              <Code2 className="w-3 h-3" />
              Source
            </button>
          </div>
        )}
        <div className="flex-1" />
        {mode === 'preview' && (
          <button
            type="button"
            onClick={() => setReloadKey(k => k + 1)}
            title="Reload preview"
            aria-label="Reload preview"
            className="inline-flex items-center gap-1 px-2 py-0.5 text-[13px] font-mono rounded cursor-pointer text-ink/65 hover:bg-surface-soft transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-sky-400/60"
          >
            <RefreshCw className="w-3 h-3" />
          </button>
        )}
        <a
          href={externalUrl}
          target="_blank"
          rel="noopener noreferrer"
          title="Open in new tab"
          aria-label="Open in new tab"
          className="inline-flex items-center gap-1 px-2 py-0.5 text-[13px] font-mono rounded cursor-pointer text-ink/65 hover:bg-surface-soft transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-sky-400/60"
        >
          <ExternalLink className="w-3 h-3" />
        </a>
      </div>

      {mode === 'source' && canEdit ? (
        <div className="flex-1 min-h-0">
          <Suspense fallback={<div className="p-4 text-xs font-mono text-ink/45">Loading editor…</div>}>
            <MonacoViewer scope={scope} path={path} editable languageOverride="html" />
          </Suspense>
        </div>
      ) : (
        <div className="flex-1 overflow-hidden bg-white">
          <iframe
            ref={iframeRef}
            key={reloadKey}
            title="HTML preview"
            srcDoc={srcDoc}
            sandbox="allow-scripts allow-forms allow-popups allow-modals"
            className="w-full h-full border-0 bg-white"
          />
        </div>
      )}
    </div>
  );
}
