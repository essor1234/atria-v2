import React from 'react';
import { cn } from '../../lib/cn';

interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  size?: 'sm' | 'md';
  variant?: 'subtle' | 'ghost' | 'inverse' | 'accent';
}

/**
 * Circular icon button — Celesnity `button-icon-circular`.
 * Always round. `subtle` on quiet surfaces, `accent` for the nebula-gradient
 * highlight control, `inverse` on dark hero washes.
 */
export function IconButton({
  className,
  size = 'sm',
  variant = 'subtle',
  children,
  ...props
}: IconButtonProps) {
  const sizes = {
    sm: 'w-9 h-9',
    md: 'w-10 h-10',
  }[size];

  const variants = {
    subtle:  'text-ink bg-surface-soft hover:bg-hairline-soft border border-hairline-soft',
    ghost:   'text-text-secondary bg-transparent hover:bg-surface-soft hover:text-ink',
    inverse: 'text-white bg-white/10 hover:bg-white/20 backdrop-blur-sm',
    accent:  'text-white bg-gradient-brand shadow-glow-nebula hover:brightness-110',
  }[variant];

  return (
    <button
      className={cn(
        'inline-flex items-center justify-center rounded-full transition-all duration-fast ease-out active:scale-[0.95]',
        sizes,
        variants,
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
