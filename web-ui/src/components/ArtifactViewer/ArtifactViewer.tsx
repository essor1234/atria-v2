import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useLocalStorage, useMediaQuery } from 'usehooks-ts';
import { PanelRightOpen, PanelRightClose, FolderTree, X } from 'lucide-react';
import { Resizable, type ResizeCallbackData } from 'react-resizable';
import { useChatStore } from '../../stores/chat';
import { useViewerTabsStore } from '../../stores/viewerTabs';
import { TabBar } from './TabBar';
import { FileTree } from './FileTree';
import { ViewerDispatcher } from './viewers';
import { LeftPaneTabs, useLeftMode } from './LeftPaneTabs';
import { ModuleGallery } from './ModuleGallery';
import { ResizeHandle } from '../ui/ResizeHandle';

const KEY_COLLAPSED = 'artifact-viewer.collapsed';
const KEY_WIDTH = 'artifact-viewer.width';
const KEY_TOP_HEIGHT = 'artifact-viewer.top-height';

const MIN_PANEL = 320;
const MAX_PANEL = 1100;
// Vertical split: top = Explorer, bottom = Editor.
const MIN_TOP = 140;      // explorer min height
const MAX_TOP = 720;      // fallback cap before the container height is measured
const MIN_BOTTOM = 140;   // editor min height (keeps the bottom zone from collapsing)

export function ArtifactViewer() {
  const currentSessionId = useChatStore(s => s.currentSessionId);

  const [collapsed, setCollapsed] = useLocalStorage<boolean>(KEY_COLLAPSED, false);
  const [panelWidth, setPanelWidth] = useLocalStorage<number>(KEY_WIDTH, 560);
  const [topHeight, setTopHeight] = useLocalStorage<number>(KEY_TOP_HEIGHT, 400);
  const [leftMode, setLeftMode] = useLeftMode();

  // Measure the inner stack so the Explorer's max height leaves room for the
  // Editor below it (attached via callback ref since the node only exists on the
  // desktop, non-collapsed branch).
  const [contentH, setContentH] = useState(0);
  const roRef = useRef<ResizeObserver | null>(null);
  const measureRef = useCallback((node: HTMLDivElement | null) => {
    roRef.current?.disconnect();
    if (node) {
      const ro = new ResizeObserver(() => setContentH(node.clientHeight));
      ro.observe(node);
      roRef.current = ro;
      setContentH(node.clientHeight);
    }
  }, []);

  // Below lg the viewer is a full-screen overlay rather than a side column, and
  // it starts collapsed so the chat keeps the full width on entry.
  const isMobile = useMediaQuery('(max-width: 1023px)');
  const [mobileShowTree, setMobileShowTree] = useState(false);
  useEffect(() => {
    if (isMobile) setCollapsed(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMobile]);

  const activeTab = useViewerTabsStore(s => {
    if (!currentSessionId) return null;
    const slice = s.tabsByConv[currentSessionId];
    if (!slice) return null;
    return slice.tabs.find(t => t.id === slice.activeId) ?? null;
  });

  // On mobile, selecting a file (activeTab gains an id) flips the overlay from
  // the file list back to the viewer automatically.
  useEffect(() => {
    if (activeTab) setMobileShowTree(false);
  }, [activeTab?.id]);

  const maxTop = contentH > 0 ? Math.max(MIN_TOP, contentH - MIN_BOTTOM) : MAX_TOP;
  const effectiveTopHeight = Math.max(MIN_TOP, Math.min(topHeight, maxTop));

  const onPanelResize = useCallback((next: number) => {
    setPanelWidth(next);
    setTreeWidth(prev => Math.min(prev, next - 2 - MIN_VIEWER));
  }, [setPanelWidth, setTreeWidth]);

  const onTreeResize = useCallback((next: number) => {
    setTreeWidth(next);
  }, [setTreeWidth]);
  // Shared defaults required by bundled .d.ts (static defaultProps not inferred by TS)
  const resizableDefaults = {
    handleSize: [8, 8] as [number, number],
    lockAspectRatio: false,
    transformScale: 1,
  };

  const onPanelResize = useCallback((_: React.SyntheticEvent, data: ResizeCallbackData) => {
    setPanelWidth(data.size.width);
  }, [setPanelWidth]);

  const onTopResize = useCallback((_: React.SyntheticEvent, data: ResizeCallbackData) => {
    setTopHeight(data.size.height);
  }, [setTopHeight]);

  if (!currentSessionId) return null;
  const convInt = parseInt(currentSessionId, 10);
  if (Number.isNaN(convInt)) return null;

  if (collapsed) {
    // Mobile: a floating button that doesn't steal width from the chat column.
    if (isMobile) {
      return (
        <button
          onClick={() => setCollapsed(false)}
          aria-label="Open artifact viewer"
          title="Open artifact viewer"
          className="fixed bottom-24 right-3 z-30 p-2.5 rounded-full bg-canvas border border-hairline-soft text-ink/70 hover:text-ink shadow-modal cursor-pointer transition-colors"
        >
          <PanelRightOpen className="w-5 h-5" />
        </button>
      );
    }
    return (
      <button
        onClick={() => setCollapsed(false)}
        aria-label="Open artifact viewer"
        title="Open artifact viewer"
        className="self-start mt-2 mr-1 p-1.5 rounded text-ink/65 hover:text-ink hover:bg-surface-soft cursor-pointer transition-colors"
      >
        <PanelRightOpen className="w-5 h-5" />
      </button>
    );
  }

  // Mobile: full-screen overlay with a master/detail switch (file list ⇄ viewer).
  if (isMobile) {
    const showTree = !activeTab || mobileShowTree;
    return (
      <div className="fixed inset-0 z-50 flex flex-col bg-canvas">
        <div className="flex items-center gap-1 border-b border-hairline-soft/60 bg-surface-soft/30 px-2 py-1.5 flex-shrink-0">
          <button
            onClick={() => setMobileShowTree(v => !v)}
            aria-label={showTree ? 'Show viewer' : 'Show files'}
            title={showTree ? 'Show viewer' : 'Show files'}
            className={`flex-shrink-0 p-2 rounded transition-colors ${
              showTree ? 'text-accent-main-100 bg-accent-main-100/10' : 'text-ink/50 hover:text-ink hover:bg-ink/6'
            }`}
          >
            <FolderTree className="w-4 h-4" />
          </button>
          <div className="flex-1 min-w-0 overflow-hidden">
            <TabBar convId={currentSessionId} />
          </div>
          <button
            onClick={() => setCollapsed(true)}
            aria-label="Close viewer"
            title="Close viewer"
            className="flex-shrink-0 p-2 rounded text-ink/45 hover:text-ink hover:bg-ink/6 cursor-pointer transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-hidden">
          {showTree ? (
            <div className="flex flex-col h-full">
              <LeftPaneTabs mode={leftMode} onChange={setLeftMode} />
              <div className="flex-1 min-h-0 overflow-hidden">
                {leftMode === 'files'
                  ? <FileTree
                      convId={currentSessionId}
                      scope={{ kind: 'conv', id: convInt }}
                      autoExpand={['.artifacts']}
                    />
                  : <ModuleGallery convId={currentSessionId} />}
              </div>
            </div>
          ) : activeTab ? (
            <ViewerDispatcher convId={convInt} tab={activeTab} />
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex h-full shadow-modal" style={{ width: panelWidth }}>

      {/* Resize the whole panel from its left (west) edge. Parent isn't clipped
          here, so the grab strip can straddle the border. */}
      <ResizeHandle
        side="left"
        width={panelWidth}
        min={MIN_PANEL}
        max={MAX_PANEL}
        onResize={onPanelResize}
        className="absolute top-0 bottom-0 -left-1 w-2 cursor-col-resize hover:bg-sky-400/30 transition-colors z-30"
      />

      {/* ── Left: file tree, full height ── */}
      <div
        className="relative flex-shrink-0 h-full overflow-hidden border-r border-hairline-soft/60 flex flex-col"
        style={{ width: effectiveTreeWidth }}
      >
        <LeftPaneTabs mode={leftMode} onChange={setLeftMode} />
        <div className="flex-1 min-h-0 overflow-hidden">
          {leftMode === 'files'
            ? <FileTree
                convId={currentSessionId}
                scope={{ kind: 'conv', id: convInt }}
                autoExpand={['.artifacts']}
              />
            : <ModuleGallery convId={currentSessionId} />}
        </div>
        {/* Resize the tree from its right edge. Kept within bounds (parent is
            overflow-hidden) so it isn't clipped. */}
        <ResizeHandle
          side="right"
          width={effectiveTreeWidth}
          min={MIN_TREE}
          max={Math.min(MAX_TREE, panelWidth - 2 - MIN_VIEWER)}
          onResize={onTreeResize}
          className="absolute top-0 bottom-0 right-0 w-2 cursor-col-resize hover:bg-sky-400/30 transition-colors z-30"
        />
      </div>

      {/* ── Right: [tab bar | collapse btn] + viewer ── */}
      <div className="flex flex-col flex-1 min-w-0 min-h-0 bg-canvas">
    // Outer panel — resizable from the left (west) edge
    <Resizable
      {...resizableDefaults}
      width={panelWidth}
      height={0}
      axis="x"
      minConstraints={[MIN_PANEL, 0]}
      maxConstraints={[MAX_PANEL, Infinity]}
      resizeHandles={['w']}
      handle={(_, ref) => (
        <div
          ref={ref as React.RefObject<HTMLDivElement>}
          className="absolute left-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-sky-400/25 transition-colors z-10"
        />
      )}
      onResize={onPanelResize}
    >
      <div ref={measureRef} className="relative flex flex-col h-full shadow-modal" style={{ width: panelWidth }}>

        {/* ── Top: explorer (file tree / modules), height-resizable ── */}
        <Resizable
          {...resizableDefaults}
          width={0}
          height={effectiveTopHeight}
          axis="y"
          minConstraints={[0, MIN_TOP]}
          maxConstraints={[Infinity, maxTop]}
          resizeHandles={['s']}
          handle={(_, ref) => (
            <div
              ref={ref as React.RefObject<HTMLDivElement>}
              className="absolute left-0 right-0 bottom-0 h-1 cursor-row-resize hover:bg-sky-400/25 transition-colors z-10"
            />
          )}
          onResize={onTopResize}
        >
          <div
            className="relative flex-shrink-0 w-full overflow-hidden border-b border-hairline-soft/60 flex flex-col"
            style={{ height: effectiveTopHeight }}
          >
            <LeftPaneTabs mode={leftMode} onChange={setLeftMode} />
            <div className="flex-1 min-h-0 overflow-hidden">
              {leftMode === 'files'
                ? <FileTree
                    convId={currentSessionId}
                    scope={{ kind: 'conv', id: convInt }}
                    autoExpand={['.artifacts']}
                  />
                : <ModuleGallery convId={currentSessionId} />}
            </div>
          </div>
        </Resizable>

        {/* ── Bottom: [tab bar | collapse btn] + viewer, fills remaining height ── */}
        <div className="flex flex-col flex-1 min-w-0 min-h-0 bg-canvas">

          {/* Tab row with collapse button pushed to far right */}
          <div className="flex items-center border-b border-hairline-soft/60 bg-surface-soft/30 flex-shrink-0 min-w-0">
            <TabBar convId={currentSessionId} />
            <button
              onClick={() => setCollapsed(true)}
              aria-label="Collapse panel"
              title="Collapse panel"
              className="flex-shrink-0 p-1.5 mr-1 rounded text-ink/35 hover:text-ink/70 hover:bg-ink/6 cursor-pointer transition-colors"
            >
              <PanelRightClose className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* File viewer */}
          <div className="flex-1 min-w-0 min-h-0">
            {activeTab ? (
              <ViewerDispatcher
                convId={convInt}
                tab={activeTab}
              />
            ) : (
              <div className="flex flex-col items-center justify-center h-full gap-2 select-none">
                <div className="w-10 h-10 rounded-full border border-hairline flex items-center justify-center text-ink/20">
                  <PanelRightOpen className="w-4 h-4" />
                </div>
                <p className="text-[12px] font-mono text-ink/35">Select a file to preview</p>
              </div>
            )}
          </div>

        </div>
      </div>
  );
}
