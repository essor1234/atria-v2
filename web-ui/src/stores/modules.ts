import { create } from 'zustand';
import { ModulesApi, type Module, type ModuleTemplate } from '../api/modules';
import { wsClient } from '../api/websocket';

export type BadgeSeverity = 'info' | 'warning' | 'danger';

export interface ModuleBadge {
  count: number;
  severity: BadgeSeverity;
}

export interface ModuleSummary {
  name: string;
  display_name: string;
  tooltip: string;
  icon_url: string | null;
  dashboard_title: string;
  dashboard_default_height: number | null;
  badge_color: BadgeSeverity | null;
}

interface State {
  modules: Module[];
  loading: boolean;
  error: string | null;
  // Dashboard / sidebar state for modules that ship a dashboard.html.
  modulesWithDashboards: ModuleSummary[];
  activeModuleDashboard: string | null;
  badges: Record<string, ModuleBadge | null>;
  refresh: () => Promise<void>;
  create: (name: string, template: ModuleTemplate, summary?: string) => Promise<Module>;
  remove: (name: string) => Promise<void>;
  openDashboard: (name: string) => void;
  closeDashboard: () => void;
  setBadge: (module: string, badge: ModuleBadge | null) => void;
}

function asBadgeSeverity(v: string | null | undefined): BadgeSeverity | null {
  return v === 'info' || v === 'warning' || v === 'danger' ? v : null;
}

function summarize(modules: Module[]): ModuleSummary[] {
  return modules
    .filter((m) => m.files.includes('dashboard.html'))
    .map((m) => {
      const mf = m.manifest ?? null;
      const iconPath = mf?.icon ?? (m.files.includes('icon.svg') ? 'icon.svg' : null);
      const display = (mf?.display_name && mf.display_name.trim()) || m.name;
      const tooltip = (mf?.tooltip && mf.tooltip.trim()) || display;
      const dash = mf?.dashboard ?? null;
      return {
        name: m.name,
        display_name: display,
        tooltip,
        icon_url: iconPath
          ? `/api/modules/${encodeURIComponent(m.name)}/${iconPath.replace(/^\/+/, '')}`
          : null,
        dashboard_title: (dash?.title && dash.title.trim()) || `${display} · dashboard`,
        dashboard_default_height: dash?.default_height ?? null,
        badge_color: asBadgeSeverity(dash?.badge_color),
      };
    });
}

export const useModulesStore = create<State>((set, get) => ({
  modules: [],
  loading: false,
  error: null,
  modulesWithDashboards: [],
  activeModuleDashboard: null,
  badges: {},

  async refresh() {
    set({ loading: true, error: null });
    try {
      const modules = await ModulesApi.list();
      const withDash = summarize(modules);
      set((state) => {
        const stillThere =
          state.activeModuleDashboard != null &&
          withDash.some((m) => m.name === state.activeModuleDashboard);
        return {
          modules,
          modulesWithDashboards: withDash,
          activeModuleDashboard: stillThere ? state.activeModuleDashboard : null,
          loading: false,
        };
      });
    } catch (e: unknown) {
      set({ error: String(e), loading: false });
    }
  },

  async create(name, template, summary) {
    const m = await ModulesApi.create(name, template, summary);
    await get().refresh();
    return m;
  },

  async remove(name) {
    await ModulesApi.remove(name);
    await get().refresh();
  },

  openDashboard: (name) => {
    const exists = get().modulesWithDashboards.some((m) => m.name === name);
    if (!exists) return;
    set({ activeModuleDashboard: name });
  },

  closeDashboard: () => set({ activeModuleDashboard: null }),

  setBadge: (module, badge) =>
    set((state) => ({ badges: { ...state.badges, [module]: badge } })),
}));

// Refresh on WS modules.changed.
wsClient.on('modules.changed', () => {
  useModulesStore.getState().refresh();
});
