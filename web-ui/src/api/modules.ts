export interface ModuleDashboardManifest {
  title?: string | null;
  default_height?: number | null;
  badge_color?: string | null;
}

export interface ModuleManifest {
  display_name?: string | null;
  tooltip?: string | null;
  icon?: string | null;
  dashboard?: ModuleDashboardManifest | null;
}

export interface Module {
  name: string;
  skill_md: string;
  mtime: number;
  files: string[];
  manifest?: ModuleManifest | null;
}

export type ModuleTemplate = 'blank' | 'skill' | 'skill_script' | 'skill_dashboard';

const BASE = '/api/modules';

export const ModulesApi = {
  async list(): Promise<Module[]> {
    const r = await fetch(BASE, { credentials: 'include' });
    if (!r.ok) throw new Error(`list modules: ${r.status}`);
    return r.json();
  },
  async get(name: string): Promise<Module> {
    const r = await fetch(`${BASE}/${encodeURIComponent(name)}`, { credentials: 'include' });
    if (!r.ok) throw new Error(`get module: ${r.status}`);
    return r.json();
  },
  async create(name: string, template: ModuleTemplate, summary?: string): Promise<Module> {
    const r = await fetch(BASE, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, template, summary: summary ?? '' }),
    });
    if (!r.ok) throw new Error(`create module: ${r.status}`);
    return r.json();
  },
  async remove(name: string): Promise<void> {
    const r = await fetch(`${BASE}/${encodeURIComponent(name)}`, {
      method: 'DELETE',
      credentials: 'include',
    });
    if (!r.ok && r.status !== 204) throw new Error(`delete module: ${r.status}`);
  },
};
