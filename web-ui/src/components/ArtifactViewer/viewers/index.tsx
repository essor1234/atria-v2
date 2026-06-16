import { Suspense, lazy } from 'react';
import { apiClient } from '../../../api/client';
import { pickRenderer } from './extensions';
import { BinaryFallback } from './BinaryFallback';
import { ImageViewer } from './ImageViewer';
import { PdfViewer } from './PdfViewer';
import { MarkdownViewer } from './MarkdownViewer';
import { HtmlViewer } from './HtmlViewer';
import { CsvViewer } from './CsvViewer';
import { ModuleEditor } from './ModuleEditor';
import type { FsScope, ViewerTab } from '../../../types';

const MonacoViewer = lazy(() =>
  import('./MonacoViewer').then(m => ({ default: m.MonacoViewer })),
);
const ExcelViewer = lazy(() =>
  import('./ExcelViewer').then(m => ({ default: m.ExcelViewer })),
);

interface Props {
  convId: number;
  tab: ViewerTab;
}

function Fallback() {
  return <div className="p-4 text-xs font-mono text-ink/45">Loading viewer…</div>;
}

export function ViewerDispatcher({ convId, tab }: Props) {
  if (tab.kind === 'module') {
    return <ModuleEditor convId={String(convId)} name={tab.name} />;
  }

  const scope: FsScope =
    tab.kind === 'module-file'
      ? { kind: 'module', name: tab.module }
      : { kind: 'conv', id: convId };
  const { path, name, ext } = tab;
  const url = apiClient.readFsUrl(scope, path);
  const editable = tab.kind === 'module-file';
  const kind = pickRenderer(ext);

  switch (kind) {
    case 'csv':
      return <CsvViewer scope={scope} path={path} />;
    case 'excel':
      return (
        <Suspense fallback={<Fallback />}>
          <ExcelViewer scope={scope} path={path} />
        </Suspense>
      );
    case 'image':
      return <ImageViewer url={url} name={name} />;
    case 'pdf':
      return <PdfViewer url={url} name={name} />;
    case 'markdown':
      return <MarkdownViewer scope={scope} path={path} editable={editable} />;
    case 'html':
      return <HtmlViewer scope={scope} path={path} editable={editable} />;
    case 'monaco':
      return (
        <Suspense fallback={<Fallback />}>
          <MonacoViewer scope={scope} path={path} editable={editable} />
        </Suspense>
      );
    case 'binary':
    default:
      return <BinaryFallback path={path} url={url} />;
  }
}
