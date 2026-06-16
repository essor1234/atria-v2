import { useEffect, useMemo, useState } from 'react';
import * as XLSX from 'xlsx';
import { apiClient } from '../../../api/client';
import { DataTable } from './DataTable';
import { BinaryFallback } from './BinaryFallback';
import { fsScopeKey, type FsScope } from '../../../types';

interface Props { scope: FsScope; path: string }

interface Sheet {
  name: string;
  columns: string[];
  rows: (string | number | null)[][];
}

export function ExcelViewer({ scope, path }: Props) {
  const [sheets, setSheets] = useState<Sheet[] | null>(null);
  const [active, setActive] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const scopeKey = useMemo(() => fsScopeKey(scope), [scope]);

  useEffect(() => {
    let cancelled = false;
    setSheets(null);
    setError(null);
    apiClient.readFsBlob(scope, path).then(async blob => {
      const buf = await blob.arrayBuffer();
      try {
        const wb = XLSX.read(buf, { type: 'array' });
        const parsed: Sheet[] = wb.SheetNames.map(name => {
          const ws = wb.Sheets[name];
          const aoa = XLSX.utils.sheet_to_json<unknown[]>(ws, { header: 1, defval: null });
          const columns = (aoa[0] ?? []).map(c => (c == null ? '' : String(c)));
          const rows = aoa.slice(1) as (string | number | null)[][];
          return { name, columns, rows };
        });
        if (!cancelled) setSheets(parsed);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    }).catch(e => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [scopeKey, path]);

  if (error) {
    return <BinaryFallback path={path} url={apiClient.readFsUrl(scope, path)} />;
  }
  if (sheets === null) {
    return <div className="p-4 text-xs font-mono text-ink/45">Parsing workbook…</div>;
  }
  const sheet = sheets[active] ?? sheets[0];
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-1 px-2 py-1 border-b border-hairline-soft overflow-x-auto">
        {sheets.map((s, i) => (
          <button
            key={s.name}
            onClick={() => setActive(i)}
            className={`px-2 py-0.5 text-[13px] font-mono rounded cursor-pointer transition-colors whitespace-nowrap ${
              i === active ? 'bg-ink/8 text-ink' : 'text-ink/65 hover:bg-surface-soft'
            }`}
          >
            {s.name}
          </button>
        ))}
      </div>
      <div className="flex-1 min-h-0">
        <DataTable columns={sheet.columns} rows={sheet.rows} truncatedFrom={sheet.rows.length} />
      </div>
    </div>
  );
}
