import { useCallback } from 'react';
import { useLocalStorage } from 'usehooks-ts';
import { PanelRightOpen, PanelRightClose } from 'lucide-react';
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
const KEY_TREE_WIDTH = 'artifact-viewer.tree-width';

const MIN_PANEL = 320;
const MAX_PANEL = 1100;
const MIN_TREE = 160;
const MAX_TREE = 480;
const MIN_VIEWER = 80;

export function ArtifactViewer() {
  const currentSessionId = useChatStore(s => s.currentSessionId);

  const [collapsed, setCollapsed] = useLocalStorage<boolean>(KEY_COLLAPSED, false);
  const [panelWidth, setPanelWidth] = useLocalStorage<number>(KEY_WIDTH, 560);
  const [treeWidth, setTreeWidth] = useLocalStorage<number>(KEY_TREE_WIDTH, 220);
  const [leftMode, setLeftMode] = useLeftMode();

  const activeTab = useViewerTabsStore(s => {
    if (!currentSessionId) return null;
    const slice = s.tabsByConv[currentSessionId];
    if (!slice) return null;
    return slice.tabs.find(t => t.id === slice.activeId) ?? null;
  });

  const effectiveTreeWidth = Math.min(treeWidth, panelWidth - 2 - MIN_VIEWER);

  const onPanelResize = useCallback((next: number) => {
    setPanelWidth(next);
    setTreeWidth(prev => Math.min(prev, next - 2 - MIN_VIEWER));
  }, [setPanelWidth, setTreeWidth]);

  const onTreeResize = useCallback((next: number) => {
    setTreeWidth(next);
  }, [setTreeWidth]);

  if (!currentSessionId) return null;
  const convInt = parseInt(currentSessionId, 10);
  if (Number.isNaN(convInt)) return null;

  if (collapsed) {
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
