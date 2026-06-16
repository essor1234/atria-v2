import { create } from 'zustand';
import { apiClient } from '../api/client';
import type { FsEntry, FsScope } from '../types';
import { fsScopeKey } from '../types';

interface TreeState {
  rootEntries: FsEntry[];
  childrenByPath: Record<string, FsEntry[]>;
  loadingPaths: Set<string>;
  expanded: Set<string>;
  showHidden: boolean;
  search: string;
  rootLoaded: boolean;
  selectedPath: string | null;
  pendingEntry: { parentPath: string; kind: 'file' | 'dir' } | null;
  renamingPath: string | null;
}

export class FsNameError extends Error {}

const INVALID_NAME_RE = /[/\\]/;
export function validateName(name: string, allowDot: boolean): string | null {
  if (!name) return 'Name cannot be empty.';
  if (name.length > 255) return 'Name too long.';
  if (INVALID_NAME_RE.test(name)) return 'Name cannot contain / or \\.';
  if (!allowDot && name.startsWith('.')) return 'Hidden names start with "." — enable Show dotfiles first.';
  return null;
}

interface FileExplorerState {
  treesByScope: Record<string, TreeState>;
  loadDir: (scope: FsScope, path: string) => Promise<void>;
  toggleExpand: (scope: FsScope, path: string) => Promise<void>;
  setShowHidden: (scope: FsScope, v: boolean) => Promise<void>;
  setSearch: (scope: FsScope, q: string) => void;
  refresh: (scope: FsScope) => Promise<void>;
  select: (scope: FsScope, path: string | null) => void;
  beginCreate: (scope: FsScope, parentPath: string, kind: 'file' | 'dir') => Promise<void>;
  cancelPending: (scope: FsScope) => void;
  confirmPending: (scope: FsScope, name: string) => Promise<void>;
  beginRename: (scope: FsScope, path: string) => void;
  cancelRename: (scope: FsScope) => void;
  confirmRename: (scope: FsScope, newName: string) => Promise<void>;
  removePath: (scope: FsScope, path: string, kind: 'file' | 'dir') => Promise<void>;
}

function emptyTree(): TreeState {
  const showHidden = localStorage.getItem('artifact-viewer.show-dotfiles') === 'true';
  return {
    rootEntries: [],
    childrenByPath: {},
    loadingPaths: new Set(),
    expanded: new Set(),
    showHidden,
    search: '',
    rootLoaded: false,
    selectedPath: null,
    pendingEntry: null,
    renamingPath: null,
  };
}

function patchTree(
  state: { treesByScope: Record<string, TreeState> },
  scope: FsScope,
  patch: Partial<TreeState>,
): { treesByScope: Record<string, TreeState> } {
  const key = fsScopeKey(scope);
  const tree = state.treesByScope[key] ?? emptyTree();
  return { treesByScope: { ...state.treesByScope, [key]: { ...tree, ...patch } } };
}

export const useFileExplorerStore = create<FileExplorerState>((set, get) => ({
  treesByScope: {},

  loadDir: async (scope, path) => {
    const key = fsScopeKey(scope);
    const trees = get().treesByScope;
    const tree = trees[key] ?? emptyTree();
    if (tree.loadingPaths.has(path)) return;

    const nextLoading = new Set(tree.loadingPaths);
    nextLoading.add(path);
    set({ treesByScope: { ...trees, [key]: { ...tree, loadingPaths: nextLoading } } });

    try {
      const resp = await apiClient.listFs(scope, path, tree.showHidden);
      const after = get().treesByScope[key] ?? tree;
      const doneLoading = new Set(after.loadingPaths);
      doneLoading.delete(path);
      const isRoot = path === '';
      set({
        treesByScope: {
          ...get().treesByScope,
          [key]: {
            ...after,
            rootEntries: isRoot ? resp.entries : after.rootEntries,
            rootLoaded: isRoot ? true : after.rootLoaded,
            childrenByPath: isRoot
              ? after.childrenByPath
              : { ...after.childrenByPath, [path]: resp.entries },
            loadingPaths: doneLoading,
          },
        },
      });
    } catch {
      const after = get().treesByScope[key] ?? tree;
      const doneLoading = new Set(after.loadingPaths);
      doneLoading.delete(path);
      set({
        treesByScope: { ...get().treesByScope, [key]: { ...after, loadingPaths: doneLoading } },
      });
    }
  },

  toggleExpand: async (scope, path) => {
    const key = fsScopeKey(scope);
    const tree = get().treesByScope[key] ?? emptyTree();
    const expanded = new Set(tree.expanded);
    if (expanded.has(path)) {
      expanded.delete(path);
      set({ treesByScope: { ...get().treesByScope, [key]: { ...tree, expanded } } });
      return;
    }
    expanded.add(path);
    set({ treesByScope: { ...get().treesByScope, [key]: { ...tree, expanded } } });
    if (!tree.childrenByPath[path]) {
      await get().loadDir(scope, path);
    }
  },

  setShowHidden: async (scope, v) => {
    const key = fsScopeKey(scope);
    localStorage.setItem('artifact-viewer.show-dotfiles', String(v));
    const tree = get().treesByScope[key] ?? emptyTree();
    set({
      treesByScope: {
        ...get().treesByScope,
        [key]: { ...tree, showHidden: v, rootLoaded: false, childrenByPath: {} },
      },
    });
    await get().loadDir(scope, '');
  },

  setSearch: (scope, q) => {
    const key = fsScopeKey(scope);
    const tree = get().treesByScope[key] ?? emptyTree();
    set({ treesByScope: { ...get().treesByScope, [key]: { ...tree, search: q } } });
  },

  refresh: async (scope) => {
    const key = fsScopeKey(scope);
    const tree = get().treesByScope[key];
    if (!tree) return;
    set({
      treesByScope: {
        ...get().treesByScope,
        [key]: { ...tree, rootLoaded: false, childrenByPath: {} },
      },
    });
    await get().loadDir(scope, '');
    for (const p of tree.expanded) {
      await get().loadDir(scope, p);
    }
  },

  select: (scope, path) => {
    set(s => patchTree(s, scope, { selectedPath: path }));
  },

  beginCreate: async (scope, parentPath, kind) => {
    const key = fsScopeKey(scope);
    const tree = get().treesByScope[key] ?? emptyTree();
    if (parentPath && !tree.expanded.has(parentPath)) {
      await get().toggleExpand(scope, parentPath);
    }
    set(s => patchTree(s, scope, {
      pendingEntry: { parentPath, kind },
      renamingPath: null,
    }));
  },

  cancelPending: (scope) => {
    set(s => patchTree(s, scope, { pendingEntry: null }));
  },

  confirmPending: async (scope, name) => {
    const key = fsScopeKey(scope);
    const tree = get().treesByScope[key];
    const pending = tree?.pendingEntry;
    if (!pending) return;
    const err = validateName(name, tree?.showHidden ?? false);
    if (err) throw new FsNameError(err);
    const fullPath = pending.parentPath ? `${pending.parentPath}/${name}` : name;
    if (pending.kind === 'file') {
      await apiClient.touchFs(scope, fullPath);
    } else {
      await apiClient.mkdirFs(scope, fullPath);
    }
    set(s => patchTree(s, scope, { pendingEntry: null }));
    // Reload the parent (or root) so the new entry appears.
    await get().loadDir(scope, pending.parentPath);
  },

  beginRename: (scope, path) => {
    set(s => patchTree(s, scope, { renamingPath: path, pendingEntry: null }));
  },

  cancelRename: (scope) => {
    set(s => patchTree(s, scope, { renamingPath: null }));
  },

  confirmRename: async (scope, newName) => {
    const key = fsScopeKey(scope);
    const tree = get().treesByScope[key];
    const from = tree?.renamingPath;
    if (!from) return;
    const err = validateName(newName, tree?.showHidden ?? false);
    if (err) throw new FsNameError(err);
    const lastSlash = from.lastIndexOf('/');
    const parent = lastSlash >= 0 ? from.slice(0, lastSlash) : '';
    const oldName = lastSlash >= 0 ? from.slice(lastSlash + 1) : from;
    if (oldName === newName) {
      set(s => patchTree(s, scope, { renamingPath: null }));
      return;
    }
    const to = parent ? `${parent}/${newName}` : newName;
    await apiClient.renameFs(scope, from, to);
    set(s => patchTree(s, scope, { renamingPath: null }));
    await get().loadDir(scope, parent);
  },

  removePath: async (scope, path, _kind) => {
    // Backend's delete endpoint handles both files (unlink) and directories (rmtree).
    await apiClient.deleteFsFile(scope, path);
    const lastSlash = path.lastIndexOf('/');
    const parent = lastSlash >= 0 ? path.slice(0, lastSlash) : '';
    set(s => patchTree(s, scope, {
      selectedPath: null,
      renamingPath: null,
    }));
    await get().loadDir(scope, parent);
  },
}));
