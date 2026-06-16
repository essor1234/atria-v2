/**
 * Univer factory for the artifact viewer's Excel surface.
 *
 * Univer holds a lot of global state (DOM, plugins, command bus). The
 * artifact viewer mounts/unmounts the ExcelViewer freely as the user
 * switches files, so we expose a thin handle whose `dispose()` tears
 * everything down cleanly.
 */
import { createUniver, LocaleType, mergeLocales } from '@univerjs/presets';
import { UniverSheetsCorePreset } from '@univerjs/preset-sheets-core';
import UniverPresetSheetsCoreEnUS from '@univerjs/preset-sheets-core/locales/en-US';

import '@univerjs/preset-sheets-core/lib/index.css';

import type { UniverWorkbook } from './xlsxBridge';

export interface UniverHandle {
  // Untyped to avoid leaking Univer types across module boundaries.
  // The ExcelViewer only needs save() and addEvent(); callers cast as needed.
  univerAPI: any;
  dispose: () => void;
}

export function createUniverInstance(
  container: HTMLDivElement,
  snapshot: UniverWorkbook,
): UniverHandle {
  const { univer, univerAPI } = createUniver({
    locale: LocaleType.EN_US,
    locales: {
      [LocaleType.EN_US]: mergeLocales(UniverPresetSheetsCoreEnUS),
    },
    presets: [UniverSheetsCorePreset({ container })],
  });
  univerAPI.createWorkbook(snapshot as any);
  return {
    univerAPI,
    dispose: () => {
      try {
        univer.dispose();
      } catch (err) {
        console.warn('[setupUniver] dispose failed', err);
      }
    },
  };
}
