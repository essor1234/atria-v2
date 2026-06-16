import { describe, it, expect, beforeEach } from 'vitest';
import { useViewerTabsStore } from './viewerTabs';

beforeEach(() => {
  useViewerTabsStore.setState({ tabsByConv: {} });
});

describe('viewerTabs store', () => {
  it('opens a tab and sets it active', () => {
    useViewerTabsStore.getState().openTab('1', 'README.md');
    const { tabs, activeId } = useViewerTabsStore.getState().tabsByConv['1'];
    expect(tabs).toHaveLength(1);
    expect(tabs[0].kind === 'file' ? tabs[0].path : '').toBe('README.md');
    expect(activeId).toBe('README.md');
  });

  it('focuses existing tab on reopen instead of duplicating', () => {
    useViewerTabsStore.getState().openTab('1', 'a.txt');
    useViewerTabsStore.getState().openTab('1', 'b.txt');
    useViewerTabsStore.getState().openTab('1', 'a.txt');
    const { tabs, activeId } = useViewerTabsStore.getState().tabsByConv['1'];
    expect(tabs.map(t => (t.kind === 'file' ? t.path : ''))).toEqual(['a.txt', 'b.txt']);
    expect(activeId).toBe('a.txt');
  });

  it('closes the active tab and shifts active to neighbor', () => {
    useViewerTabsStore.getState().openTab('1', 'a.txt');
    useViewerTabsStore.getState().openTab('1', 'b.txt');
    useViewerTabsStore.getState().openTab('1', 'c.txt');
    useViewerTabsStore.getState().closeTab('1', 'b.txt');
    const { tabs, activeId } = useViewerTabsStore.getState().tabsByConv['1'];
    expect(tabs.map(t => (t.kind === 'file' ? t.path : ''))).toEqual(['a.txt', 'c.txt']);
    expect(activeId).toBe('c.txt');
  });

  it('closing the last tab leaves activeId null', () => {
    useViewerTabsStore.getState().openTab('1', 'only.txt');
    useViewerTabsStore.getState().closeTab('1', 'only.txt');
    const slice = useViewerTabsStore.getState().tabsByConv['1'];
    expect(slice.tabs).toEqual([]);
    expect(slice.activeId).toBeNull();
  });
});
