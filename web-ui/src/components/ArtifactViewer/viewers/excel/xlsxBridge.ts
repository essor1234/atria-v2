/**
 * Bridge between SheetJS workbooks and Univer's IWorkbookData snapshot.
 *
 * Univer OSS doesn't ship xlsx I/O; this module is the conversion layer.
 * Pure functions, no DOM / Univer runtime dependency — kept this way so the
 * round-trip can be unit tested without spinning up a Univer instance.
 */
import * as XLSX from 'xlsx';

// Mirror Univer's numeric enums (kept inline so this module has no
// @univerjs/* runtime dependency).
const CELL_VALUE_TYPE = {
  STRING: 1,
  NUMBER: 2,
  BOOLEAN: 3,
  FORCE_STRING: 4,
} as const;

interface UniverCell {
  v?: string | number | boolean | null;
  f?: string;
  t?: number;
  // styles + rich text intentionally omitted; v0 keeps fidelity to values+formulas.
}

type CellMatrix = Record<number, Record<number, UniverCell>>;

interface UniverSheet {
  id: string;
  name: string;
  tabColor: string;
  hidden: 0 | 1;
  freeze: { startRow: number; startColumn: number; ySplit: number; xSplit: number };
  rowCount: number;
  columnCount: number;
  zoomRatio: number;
  scrollTop: number;
  scrollLeft: number;
  defaultColumnWidth: number;
  defaultRowHeight: number;
  mergeData: { startRow: number; startColumn: number; endRow: number; endColumn: number }[];
  cellData: CellMatrix;
  rowData: Record<number, { h: number }>;
  columnData: Record<number, { w: number }>;
  showGridlines: 0 | 1;
  rowHeader: { width: number; hidden: 0 | 1 };
  columnHeader: { height: number; hidden: 0 | 1 };
  rightToLeft: 0 | 1;
}

export interface UniverWorkbook {
  id: string;
  rev: number;
  name: string;
  appVersion: string;
  locale: string;
  styles: Record<string, unknown>;
  sheetOrder: string[];
  sheets: Record<string, UniverSheet>;
}

const DEFAULT_ROW_COUNT = 1000;
const DEFAULT_COL_COUNT = 26;
const DEFAULT_COL_W = 88;
const DEFAULT_ROW_H = 24;

function sanitizeId(name: string, idx: number): string {
  const cleaned = name.replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 32);
  return `sheet-${idx}-${cleaned || 'untitled'}`;
}

function sheetjsCellToUniver(c: XLSX.CellObject): UniverCell {
  const cell: UniverCell = {};
  if (c.f) {
    // SheetJS stores formula text WITHOUT the leading '='.
    cell.f = c.f.startsWith('=') ? c.f : `=${c.f}`;
  }
  switch (c.t) {
    case 'n':
      cell.v = typeof c.v === 'number' ? c.v : Number(c.v);
      cell.t = CELL_VALUE_TYPE.NUMBER;
      break;
    case 's':
      cell.v = c.v == null ? '' : String(c.v);
      cell.t = CELL_VALUE_TYPE.STRING;
      break;
    case 'b':
      cell.v = c.v ? 1 : 0;
      cell.t = CELL_VALUE_TYPE.BOOLEAN;
      break;
    case 'd': {
      // Convert Date to Excel serial number (days since 1899-12-30).
      const d = c.v instanceof Date ? c.v : new Date(String(c.v));
      const epoch = Date.UTC(1899, 11, 30);
      const serial = (d.getTime() - epoch) / 86400000;
      cell.v = serial;
      cell.t = CELL_VALUE_TYPE.NUMBER;
      break;
    }
    case 'e':
      cell.v = c.w ?? '#ERR';
      cell.t = CELL_VALUE_TYPE.FORCE_STRING;
      break;
    case 'z':
    default:
      if (c.v != null) {
        cell.v = String(c.v);
        cell.t = CELL_VALUE_TYPE.STRING;
      }
      break;
  }
  return cell;
}

function univerCellToSheetjs(cell: UniverCell): XLSX.CellObject | null {
  const hasFormula = typeof cell.f === 'string' && cell.f.length > 0;
  const hasValue = cell.v !== undefined && cell.v !== null;
  if (!hasFormula && !hasValue) return null;

  const out: XLSX.CellObject = { t: 's', v: '' };

  if (hasFormula) {
    // Strip the leading '=' for SheetJS.
    out.f = (cell.f as string).startsWith('=')
      ? (cell.f as string).slice(1)
      : (cell.f as string);
  }

  switch (cell.t) {
    case CELL_VALUE_TYPE.NUMBER:
      out.t = 'n';
      out.v = typeof cell.v === 'number' ? cell.v : Number(cell.v);
      break;
    case CELL_VALUE_TYPE.BOOLEAN:
      out.t = 'b';
      out.v = !!cell.v;
      break;
    case CELL_VALUE_TYPE.FORCE_STRING:
    case CELL_VALUE_TYPE.STRING:
      out.t = 's';
      out.v = cell.v == null ? '' : String(cell.v);
      break;
    default:
      // Infer from value.
      if (typeof cell.v === 'number') {
        out.t = 'n';
        out.v = cell.v;
      } else if (typeof cell.v === 'boolean') {
        out.t = 'b';
        out.v = cell.v;
      } else {
        out.t = 's';
        out.v = cell.v == null ? '' : String(cell.v);
      }
      break;
  }
  return out;
}

function buildUniverSheet(wb: XLSX.WorkBook, name: string, idx: number): UniverSheet {
  const ws = wb.Sheets[name];
  const ref = ws['!ref'] ?? 'A1:A1';
  const range = XLSX.utils.decode_range(ref);
  const rowCount = Math.max(DEFAULT_ROW_COUNT, range.e.r + 1);
  const columnCount = Math.max(DEFAULT_COL_COUNT, range.e.c + 1);

  const cellData: CellMatrix = {};
  for (let r = range.s.r; r <= range.e.r; r++) {
    for (let c = range.s.c; c <= range.e.c; c++) {
      const addr = XLSX.utils.encode_cell({ r, c });
      const cell = ws[addr] as XLSX.CellObject | undefined;
      if (!cell) continue;
      const converted = sheetjsCellToUniver(cell);
      if (converted.v === undefined && converted.f === undefined) continue;
      if (!cellData[r]) cellData[r] = {};
      cellData[r][c] = converted;
    }
  }

  const mergeData = (ws['!merges'] ?? []).map((m) => ({
    startRow: m.s.r,
    startColumn: m.s.c,
    endRow: m.e.r,
    endColumn: m.e.c,
  }));

  const columnData: Record<number, { w: number }> = {};
  (ws['!cols'] ?? []).forEach((col, i) => {
    if (col && typeof col.wpx === 'number') columnData[i] = { w: col.wpx };
  });

  const rowData: Record<number, { h: number }> = {};
  (ws['!rows'] ?? []).forEach((row, i) => {
    if (row && typeof row.hpx === 'number') rowData[i] = { h: row.hpx };
  });

  return {
    id: sanitizeId(name, idx),
    name,
    tabColor: '',
    hidden: 0,
    freeze: { startRow: -1, startColumn: -1, ySplit: 0, xSplit: 0 },
    rowCount,
    columnCount,
    zoomRatio: 1,
    scrollTop: 0,
    scrollLeft: 0,
    defaultColumnWidth: DEFAULT_COL_W,
    defaultRowHeight: DEFAULT_ROW_H,
    mergeData,
    cellData,
    rowData,
    columnData,
    showGridlines: 1,
    rowHeader: { width: 46, hidden: 0 },
    columnHeader: { height: 20, hidden: 0 },
    rightToLeft: 0,
  };
}

export function workbookToSnapshot(wb: XLSX.WorkBook): UniverWorkbook {
  const sheetNames = wb.SheetNames.filter((n) => !!wb.Sheets[n]);
  const sheets: Record<string, UniverSheet> = {};
  const sheetOrder: string[] = [];
  sheetNames.forEach((name, i) => {
    const sheet = buildUniverSheet(wb, name, i);
    sheets[sheet.id] = sheet;
    sheetOrder.push(sheet.id);
  });
  return {
    id: 'workbook-1',
    rev: 1,
    name: 'workbook',
    appVersion: '0.25.0',
    locale: 'enUS',
    styles: {},
    sheetOrder: sheetOrder.length ? sheetOrder : ['sheet-0-empty'],
    sheets: sheetOrder.length
      ? sheets
      : {
          'sheet-0-empty': buildUniverSheet(
            { SheetNames: ['Sheet1'], Sheets: { Sheet1: { '!ref': 'A1:A1' } } } as XLSX.WorkBook,
            'Sheet1',
            0,
          ),
        },
  };
}

function buildSheetjsWorksheet(sheet: UniverSheet): XLSX.WorkSheet {
  const ws: XLSX.WorkSheet = {};
  let maxR = 0;
  let maxC = 0;
  for (const [rStr, row] of Object.entries(sheet.cellData ?? {})) {
    const r = Number(rStr);
    for (const [cStr, cell] of Object.entries(row)) {
      const c = Number(cStr);
      const converted = univerCellToSheetjs(cell);
      if (!converted) continue;
      ws[XLSX.utils.encode_cell({ r, c })] = converted;
      if (r > maxR) maxR = r;
      if (c > maxC) maxC = c;
    }
  }
  ws['!ref'] = XLSX.utils.encode_range({ s: { r: 0, c: 0 }, e: { r: maxR, c: maxC } });

  if (sheet.mergeData?.length) {
    ws['!merges'] = sheet.mergeData.map((m) => ({
      s: { r: m.startRow, c: m.startColumn },
      e: { r: m.endRow, c: m.endColumn },
    }));
  }

  const cols: XLSX.ColInfo[] = [];
  for (const [iStr, info] of Object.entries(sheet.columnData ?? {})) {
    cols[Number(iStr)] = { wpx: info.w };
  }
  if (cols.length) ws['!cols'] = cols;

  const rows: XLSX.RowInfo[] = [];
  for (const [iStr, info] of Object.entries(sheet.rowData ?? {})) {
    rows[Number(iStr)] = { hpx: info.h };
  }
  if (rows.length) ws['!rows'] = rows;

  return ws;
}

export function snapshotToWorkbook(snap: UniverWorkbook): XLSX.WorkBook {
  const wb = XLSX.utils.book_new();
  for (const id of snap.sheetOrder) {
    const sheet = snap.sheets[id];
    if (!sheet) continue;
    const ws = buildSheetjsWorksheet(sheet);
    XLSX.utils.book_append_sheet(wb, ws, sheet.name);
  }
  return wb;
}
