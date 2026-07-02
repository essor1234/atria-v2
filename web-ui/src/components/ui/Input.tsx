import React, { forwardRef } from 'react';
import { cn } from '../../lib/cn';

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  leftIcon?: React.ReactNode;
}

/**
 * Text input — Celesnity field. Hairline border on a quiet surface; focus is
 * communicated with the cobalt focus ring, never a jarring fill change.
 */
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { leftIcon, className, ...props },
  ref
) {
  return (
    <div className={cn('relative', className)}>
      {leftIcon && (
        <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-text-muted">
          {leftIcon}
        </span>
      )}
      <input
        ref={ref}
        {...props}
        className={cn(
          'w-full bg-surface-soft text-ink placeholder:text-text-muted rounded-sm border border-hairline-soft outline-none',
          'transition-shadow duration-fast focus:border-accent-cobalt focus:shadow-focus-ring',
          leftIcon ? 'pl-10 pr-4 py-3 text-[16px]' : 'px-4 py-3 text-[16px]'
        )}
      />
    </div>
  );
});
