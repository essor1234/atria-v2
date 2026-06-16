import React from 'react';

type ButtonVariant = 'primary' | 'secondary' | 'magenta' | 'ghost' | 'link' |
  // legacy aliases — mapped onto the Figma-system variants
  'default' | 'destructive' | 'outline';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: 'sm' | 'md';
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', ...props }, ref) => {
    const base =
      'inline-flex items-center justify-center whitespace-nowrap font-sans transition-transform duration-fast disabled:pointer-events-none disabled:opacity-50 hover:scale-[1.02] active:scale-[0.98]';

    const sizes = {
      sm: 'text-[14px] leading-[1.4] tracking-[-0.06px] px-4 py-[6px] rounded-pill',
      md: 'text-btn px-6 py-[10px] rounded-pill',
    }[size];

    const v: Record<ButtonVariant, string> = {
      primary:   'bg-ink text-inverse-ink',
      secondary: 'bg-canvas text-ink border border-hairline-soft hover:border-ink',
      magenta:   'bg-accent-magenta text-inverse-ink',
      ghost:     'bg-transparent text-ink hover:bg-surface-soft',
      link:      'bg-transparent text-ink underline underline-offset-4 hover:decoration-2 rounded-none px-0',
      default:     'bg-ink text-inverse-ink',
      destructive: 'bg-block-coral text-ink',
      outline:     'bg-canvas text-ink border border-hairline-soft hover:border-ink',
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
