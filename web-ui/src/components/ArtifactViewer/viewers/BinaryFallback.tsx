import { File as FileIcon, Download } from 'lucide-react';

interface Props {
  path: string;
  size?: number;
  url: string;
}

function formatSize(n?: number): string {
  if (n == null) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

export function BinaryFallback({ path, size, url }: Props) {
  const name = path.split('/').pop() ?? path;
  return (
    <div className="flex flex-col items-center justify-center h-full text-ink/65 gap-3 p-6">
      <FileIcon className="w-10 h-10 text-ink/45" />
      <p className="font-mono text-sm">{name}</p>
      {size !== undefined && <p className="font-mono text-xs text-ink/45">{formatSize(size)}</p>}
      <a
        href={url}
        download={name}
        className="inline-flex items-center gap-1.5 text-xs font-mono text-ink hover:underline cursor-pointer"
      >
        <Download className="w-3.5 h-3.5" /> Download
      </a>
    </div>
  );
}
