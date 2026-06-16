import React from 'react';
import { cn } from '../../lib/cn';

interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  size?: 'sm' | 'md';
  variant?: 'subtle' | 'ghost' | 'inverse';
}

/**
 * Circular icon button — Figma `button-icon-circular`.
 * Always rounded-full. `subtle` on light surfaces, `inverse` on dark.
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
    subtle:  'text-ink bg-surface-soft hover:bg-hairline-soft',
    ghost:   'text-ink bg-transparent hover:bg-surface-soft',
    inverse: 'text-inverse-ink bg-white/15 hover:bg-white/25',
  }[variant];

  return (
    <button
      className={cn(
        'inline-flex items-center justify-center rounded-full transition-colors duration-fast',
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
