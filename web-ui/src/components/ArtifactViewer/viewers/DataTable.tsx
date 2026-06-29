interface Props {
  columns: string[];
  rows: (string | number | null | undefined)[][];
  truncatedFrom?: number;
  maxRows?: number;
  editable?: boolean;
  onCellChange?: (rowIndex: number, colIndex: number, value: string) => void;
  onColumnChange?: (colIndex: number, value: string) => void;
}

const DEFAULT_MAX = 5000;

export function DataTable({
  columns,
  rows,
  truncatedFrom,
  maxRows = DEFAULT_MAX,
  editable = false,
  onCellChange,
  onColumnChange,
}: Props) {
  const capped = rows.slice(0, maxRows);
  const editableProps = editable
    ? {
        contentEditable: true,
        suppressContentEditableWarning: true,
        spellCheck: false,
      }
    : {};
  return (
    <div className="flex flex-col h-full">
      {truncatedFrom !== undefined && truncatedFrom > maxRows && (
        <div className="px-3 py-1.5 text-[13px] font-mono text-block-coral border-b border-hairline-soft bg-surface-soft/70">
          Showing {maxRows.toLocaleString()} of {truncatedFrom.toLocaleString()} rows
          {editable && ' — edits beyond this window are not persisted'}
        </div>
      )}
      <div className="flex-1 overflow-auto">
        <table className="text-[13px] font-mono w-max min-w-full border-collapse">
          <thead className="sticky top-0 bg-canvas backdrop-blur z-10">
            <tr>
              {columns.map((c, i) => (
                <th
                  key={i}
                  className={`text-left px-2 py-1 border-b border-hairline text-ink/80 whitespace-nowrap ${
                    editable ? 'outline-none focus:bg-surface-soft' : ''
                  }`}
                  {...editableProps}
                  onBlur={
                    editable && onColumnChange
                      ? (e) => onColumnChange(i, e.currentTarget.textContent ?? '')
                      : undefined
                  }
                >
                  {c || `col${i + 1}`}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {capped.map((row, ri) => (
              <tr key={ri} className="hover:bg-surface-soft/60">
                {columns.map((_, ci) => (
                  <td
                    key={ci}
                    className={`px-2 py-0.5 border-b border-hairline-soft text-ink whitespace-nowrap ${
                      editable ? 'outline-none focus:bg-surface-soft' : ''
                    }`}
                    {...editableProps}
                    onBlur={
                      editable && onCellChange
                        ? (e) => onCellChange(ri, ci, e.currentTarget.textContent ?? '')
                        : undefined
                    }
                  >
                    {row[ci] == null ? '' : String(row[ci])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
