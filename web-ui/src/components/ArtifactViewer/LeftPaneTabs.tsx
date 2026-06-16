import { useLocalStorage } from 'usehooks-ts';

export type LeftMode = 'files' | 'modules';

interface Props {
  mode: LeftMode;
  onChange: (m: LeftMode) => void;
}

export function LeftPaneTabs({ mode, onChange }: Props) {
  const btn = (m: LeftMode, label: string) => (
    <button
      key={m}
      onClick={() => onChange(m)}
      className={[
        'px-2 py-1 text-xs rounded transition-colors cursor-pointer',
        mode === m
          ? 'bg-surface-soft text-ink'
          : 'text-ink/55 hover:text-ink hover:bg-surface-soft/60',
      ].join(' ')}
    >
      {label}
    </button>
  );
  return (
    <div className="flex items-center gap-1 px-2 py-1 border-b border-hairline-soft/60 flex-shrink-0">
      {btn('files', 'Files')}
      {btn('modules', 'Modules')}
    </div>
  );
}

export function useLeftMode() {
  return useLocalStorage<LeftMode>('artifact-viewer.left-mode', 'files');
}
