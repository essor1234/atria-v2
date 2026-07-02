import { cn } from '../../lib/cn';

export interface SegmentOption<T extends string> {
  label: string;
  value: T;
}

interface SegmentedControlProps<T extends string> {
  options: SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}

/**
 * Segmented control — a pill track of quiet options with a single active
 * segment lifted onto the raised surface. Celesnity pill radii throughout.
 */
export function SegmentedControl<T extends string>({ options, value, onChange, className }: SegmentedControlProps<T>) {
  return (
    <div className={cn('inline-flex items-center gap-1 p-1 bg-surface-soft rounded-pill border border-hairline-soft', className)}>
      {options.map(opt => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            className={cn(
              'px-3 py-1 text-xs font-medium rounded-pill transition-all duration-fast ease-out',
              active
                ? 'bg-gradient-brand text-white shadow-glow-nebula'
                : 'text-text-secondary hover:text-ink'
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
