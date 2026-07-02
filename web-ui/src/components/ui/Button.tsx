import React from 'react';

type ButtonVariant = 'primary' | 'secondary' | 'accent' | 'magenta' | 'ghost' | 'link' |
  // legacy aliases — mapped onto the Celesnity variants
  'default' | 'destructive' | 'outline';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: 'sm' | 'md' | 'lg';
}

/**
 * Celesnity Button — the brand's primary action.
 * `primary` fills with the nebula gradient and carries a soft glow; `secondary`
 * is a calm glass surface; `ghost` is text-only. Pill radius, confident scale.
 */
const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', ...props }, ref) => {
    const base =
      'inline-flex items-center justify-center gap-2 whitespace-nowrap font-sans font-[600] tracking-[-0.01em] rounded-pill transition-all duration-fast ease-out disabled:pointer-events-none disabled:opacity-45 hover:brightness-110 active:scale-[0.97]';

    const sizes = {
      sm: 'text-[14px] leading-none px-4 py-[9px] min-h-[38px]',
      md: 'text-[16px] leading-none px-6 py-[13px] min-h-[48px]',
      lg: 'text-[17px] leading-none px-8 py-[17px] min-h-[56px]',
    }[size];

    const v: Record<ButtonVariant, string> = {
      primary:   'bg-gradient-brand text-white border-none shadow-glow-nebula',
      secondary: 'glass-card text-ink hover:bg-surface-soft',
      accent:    'bg-accent-cobalt text-white border-none shadow-glow-accent',
      magenta:   'bg-accent-magenta text-white border-none shadow-glow-magenta',
      ghost:     'bg-transparent text-text-secondary hover:bg-surface-soft hover:text-ink',
      link:      'bg-transparent text-ink underline underline-offset-4 hover:decoration-2 rounded-none px-0 min-h-0',
      default:     'bg-gradient-brand text-white border-none shadow-glow-nebula',
      destructive: 'bg-block-coral text-white border-none',
      outline:     'glass-card text-ink hover:bg-surface-soft',
    };

    return (
      <button
        className={`${base} ${sizes} ${v[variant]} ${className || ''}`}
        ref={ref}
        {...props}
      />
    );
  }
);

Button.displayName = 'Button';

export { Button };
