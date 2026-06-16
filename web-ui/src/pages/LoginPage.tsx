import { useState, FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, useReducedMotion } from 'motion/react';
import { apiClient } from '../api/client';
import { Eyebrow } from '../components/ui/Eyebrow';
import { AnimatedHeadline } from '../components/ui/AnimatedHeadline';
import { MotionRise, transitions } from '../components/ui/motion';

export function LoginPage() {
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const reduce = useReducedMotion();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await apiClient.login(email);
      navigate('/chat', { replace: true });
    } catch (err: any) {
      setError(err.message ?? 'Login failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen w-full bg-canvas grid grid-cols-1 md:grid-cols-2">
      {/* Left: lilac hero block */}
      <aside className="bg-block-lilac text-ink flex flex-col justify-between p-10 md:p-16 lg:p-20 md:min-h-screen overflow-hidden">
        <MotionRise>
          <Eyebrow className="text-ink/80">Atria · Build mode</Eyebrow>
        </MotionRise>

        <div className="max-w-xl">
          <AnimatedHeadline
            text={'Where the work\ntakes shape.'}
            className="text-[40px] md:text-display-lg lg:text-display-xl font-sans font-[340] leading-[1.02] tracking-[-0.96px] lg:tracking-[-1.72px]"
            step={18}
            startDelay={120}
          />
          <motion.p
            initial={reduce ? false : { opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ ...transitions.editorial, delay: 0.65 }}
            className="mt-8 text-body-lg max-w-md"
          >
            A canvas, a console, and a collaborator — one editorial workspace for building software with Atria.
          </motion.p>
        </div>

        <MotionRise delay={0.9}>
          <Eyebrow className="text-ink/60">v1 · 2026</Eyebrow>
        </MotionRise>
      </aside>

      {/* Right: white form */}
      <main className="flex items-center justify-center p-10 md:p-16">
        <motion.div
          initial={reduce ? false : { opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...transitions.editorial, delay: 0.25 }}
          className="w-full max-w-sm"
        >
          <Eyebrow className="text-ink/70">Sign in</Eyebrow>
          <h2 className="mt-4 text-headline tracking-[-0.26px] font-[540]">
            Continue with email
          </h2>
          <p className="mt-3 text-body-sm text-ink/70">
            We&rsquo;ll send a magic link to your inbox.
          </p>

          <form onSubmit={handleSubmit} className="mt-10">
            <label className="block">
              <Eyebrow className="mb-3 block text-ink/70">Email address</Eyebrow>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
                autoFocus
                className="w-full bg-canvas text-ink placeholder:text-ink/30 rounded-md border border-hairline-soft px-4 py-3 text-body-sm outline-none"
              />
            </label>

            {error && (
              <p className="mt-3 text-body-sm text-semantic-danger font-[540]">{error}</p>
            )}

            <motion.button
              type="submit"
              disabled={loading || !email}
              whileHover={reduce || loading || !email ? undefined : { scale: 1.01 }}
              whileTap={reduce || loading || !email ? undefined : { scale: 0.98 }}
              transition={transitions.tactile}
              className="mt-8 w-full rounded-pill bg-ink text-inverse-ink text-btn px-6 py-3 active:scale-[0.98] whitespace-nowrap disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {loading ? 'Signing in…' : 'Continue'}
            </motion.button>
          </form>

          <p className="mt-12 text-body-sm text-ink/60">
            New here? An account will be created automatically.
          </p>
        </motion.div>
      </main>
    </div>
  );
}
