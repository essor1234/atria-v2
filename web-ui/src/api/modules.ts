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
  description: string;
  mtime: number;
  files: string[];
  manifest?: ModuleManifest | null;
}

export type ModuleTemplate = 'blank' | 'skill' | 'skill_script' | 'skill_dashboard' | 'data';

export interface UploadFileEntry {
  file: File;
  relPath: string;
}

export interface DataUploadResult {
  written: string[];
  converted: string[];
  skipped: { file: string; error: string }[];
}

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
  async uploadData(
    name: string,
    files: UploadFileEntry[],
    convertXlsx = true,
  ): Promise<DataUploadResult> {
    const fd = new FormData();
    for (const { file, relPath } of files) {
      fd.append('files', file, file.name);
      fd.append('rel_paths', relPath || file.name);
    }
    fd.append('convert_xlsx', convertXlsx ? 'true' : 'false');
    const r = await fetch(`${BASE}/${encodeURIComponent(name)}/data/upload`, {
      method: 'POST',
      credentials: 'include',
      body: fd,
    });
    if (!r.ok) {
      let detail = `${r.status}`;
      try { detail = (await r.json()).detail ?? detail; } catch { /* ignore */ }
      throw new Error(`upload data: ${detail}`);
    }
    return r.json();
  },
};
