import React from 'react';

interface EyebrowProps extends React.HTMLAttributes<HTMLSpanElement> {
  as?: 'span' | 'div' | 'p';
}

/**
 * Mono uppercase category label — Figma `{typography.eyebrow}` / `{typography.caption}`.
 * Reserved for taxonomy, never used for body copy.
 */
export function Eyebrow({ as: Tag = 'span', className, children, ...rest }: EyebrowProps) {
  return (
    <Tag
      {...rest}
      className={[
        'font-sans uppercase tracking-[0.24em] text-[13px] leading-none font-[500]',
        'text-text-secondary',
        className ?? '',
      ].join(' ')}
    >
      {children}
    </Tag>
  );
}
