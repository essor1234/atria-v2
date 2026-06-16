/**
 * Motion primitives — editorial reveals tuned to DESIGN.md.
 *
 * Tone: shadow-light, confident, never bouncy. Color blocks rise like a poster
 * being placed on the wall; pills give tactile micro-feedback on press; chrome
 * stays snappy (≤200ms). All variants respect `prefers-reduced-motion`.
 */

import { motion, useReducedMotion, type Variants, type Transition } from 'motion/react';
import React, { forwardRef } from 'react';

/** Spec'd transitions — keep these as the only sources of truth. */
const editorial: Transition = { duration: 0.5, ease: [0.22, 1, 0.36, 1] }; // posters
const chrome: Transition    = { duration: 0.2, ease: [0.4, 0, 0.2, 1] };   // chrome
const tactile: Transition   = { type: 'spring', stiffness: 500, damping: 30 };

export const transitions = { editorial, chrome, tactile };

/** Slide-up reveal — assistant turns, color blocks, posters. */
export const riseUp: Variants = {
  hidden:  { opacity: 0, y: 18 },
  visible: { opacity: 1, y: 0, transition: editorial },
};

/** Soft fade — chrome elements (nav, badges, dropdowns). */
export const softFade: Variants = {
  hidden:  { opacity: 0 },
  visible: { opacity: 1, transition: chrome },
};

/** Editorial paragraph — used for body copy under a hero headline. */
export const drift: Variants = {
  hidden:  { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: { ...editorial, duration: 0.6, delay: 0.15 } },
};

/** Wrap a child element with a one-shot rise-up scroll reveal. */
interface MotionRiseProps extends React.ComponentProps<typeof motion.div> {
  delay?: number;
  /** When true, fires on viewport entry; when false, fires immediately on mount. */
  whenInView?: boolean;
}

export const MotionRise = forwardRef<HTMLDivElement, MotionRiseProps>(function MotionRise(
  { delay = 0, whenInView = false, children, transition, ...rest },
  ref
) {
  const reduce = useReducedMotion();
  const tr: Transition = reduce
    ? { duration: 0 }
    : { ...editorial, delay };
  const viewProps = whenInView
    ? { initial: 'hidden', whileInView: 'visible', viewport: { once: true, amount: 0.2 } }
    : { initial: 'hidden', animate: 'visible' };
  return (
    <motion.div
      ref={ref}
      variants={riseUp}
      transition={transition ?? tr}
      {...viewProps}
      {...rest}
    >
      {children}
    </motion.div>
  );
});

/** A tactile pill — primary CTA with whileTap + whileHover micro-scale. */
interface MotionPillProps extends React.ComponentProps<typeof motion.button> {
  variant?: 'primary' | 'secondary';
}

export const MotionPill = forwardRef<HTMLButtonElement, MotionPillProps>(function MotionPill(
  { variant = 'primary', className, children, ...rest },
  ref
) {
  const reduce = useReducedMotion();
  const base =
    'inline-flex items-center justify-center whitespace-nowrap rounded-pill text-btn px-6 py-[10px] font-sans transition-colors duration-fast active:scale-[0.98] disabled:opacity-40 disabled:cursor-not-allowed';
  const v = variant === 'primary'
    ? 'bg-ink text-inverse-ink'
    : 'bg-canvas text-ink border border-hairline-soft hover:border-ink';
  return (
    <motion.button
      ref={ref}
      whileHover={reduce ? undefined : { scale: 1.02 }}
      whileTap={reduce ? undefined : { scale: 0.97 }}
      transition={tactile}
      className={`${base} ${v} ${className ?? ''}`}
      {...rest}
    >
      {children}
    </motion.button>
  );
});
