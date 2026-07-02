import { useEffect, useState, FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, useReducedMotion } from 'motion/react';
import { apiClient } from '../api/client';
import { Eyebrow } from '../components/ui/Eyebrow';
import { AnimatedHeadline } from '../components/ui/AnimatedHeadline';
import { MotionRise, transitions } from '../components/ui/motion';

type AuthMode = 'keycloak' | 'none' | 'loading';

export function LoginPage() {
  const [mode, setMode] = useState<AuthMode>('loading');
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const reduce = useReducedMotion();

  useEffect(() => {
    apiClient
      .authMode()
      .then((m) => setMode(m.mode))
      .catch(() => setMode('none'));
  }, []);

  function handleSso() {
    setError('');
    setLoading(true);
    window.location.href = apiClient.keycloakLoginUrl('/chat');
  }

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
      {/* Left: cosmic hero wash — the nebula always glows here, both themes. */}
      <aside className="relative isolate bg-hero-wash text-white flex flex-col justify-between p-10 md:p-16 lg:p-20 md:min-h-screen overflow-hidden">
        {/* Signature nebula glow — a soft off-canvas bloom. */}
        <div
          aria-hidden
          className="pointer-events-none absolute -top-24 -left-24 w-[28rem] h-[28rem] rounded-full bg-gradient-brand opacity-40 blur-3xl"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute bottom-[-10rem] right-[-6rem] w-[24rem] h-[24rem] rounded-full bg-gradient-brand opacity-25 blur-3xl"
        />

        <MotionRise>
          <Eyebrow className="!text-white/70">Atria · Build mode</Eyebrow>
        </MotionRise>

        <div className="relative max-w-xl">
          <AnimatedHeadline
            text={'Where the work\ntakes shape.'}
            className="text-[40px] md:text-display-lg lg:text-display-xl font-sans font-[600] leading-[1.02] tracking-[-0.03em] text-white"
            step={18}
            startDelay={120}
          />
          <motion.p
            initial={reduce ? false : { opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ ...transitions.editorial, delay: 0.65 }}
            className="mt-8 text-body-lg max-w-md text-white/70"
          >
            A canvas, a console, and a collaborator — one editorial workspace for building software with Atria.
          </motion.p>
        </div>

        <MotionRise delay={0.9}>
          <Eyebrow className="!text-white/45">v1 · 2026</Eyebrow>
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
          <Eyebrow className="text-text-secondary">Sign in</Eyebrow>

          {mode === 'loading' && (
            <p className="mt-6 text-body-sm text-text-muted">Loading…</p>
          )}

          {mode === 'keycloak' && (
            <>
              <h2 className="mt-4 text-headline tracking-[-0.26px] font-[600] text-ink">
                Continue with SSO
              </h2>
              <p className="mt-3 text-body-sm text-text-secondary">
                Authenticate through your organization&rsquo;s identity provider.
              </p>

              <Eyebrow className="mt-10 block text-text-muted">
                Identity provider · Keycloak
              </Eyebrow>

              {error && (
                <p className="mt-3 text-body-sm text-semantic-danger font-[540]">{error}</p>
              )}

              <motion.button
                type="button"
                onClick={handleSso}
                disabled={loading}
                whileHover={reduce || loading ? undefined : { opacity: 0.92 }}
                whileTap={reduce || loading ? undefined : { scale: 0.98 }}
                transition={transitions.tactile}
                style={{ minWidth: '240px' }}
                className="mt-4 inline-flex items-center justify-center gap-2 rounded-pill bg-gradient-brand text-white shadow-glow-nebula text-btn px-6 py-3 whitespace-nowrap disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {loading ? (
                  <>
                    <svg
                      className="h-4 w-4 animate-spin"
                      viewBox="0 0 24 24"
                      fill="none"
                      aria-hidden="true"
                    >
                      <circle
                        cx="12"
                        cy="12"
                        r="9"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeDasharray="14 42"
                        opacity="0.9"
                      />
                    </svg>
                    <span>Redirecting</span>
                  </>
                ) : (
                  <span>Continue with Keycloak</span>
                )}
              </motion.button>

              <p className="mt-12 text-body-sm text-text-muted">
                You will be redirected to the identity provider, then returned here.
              </p>
            </>
          )}

          {mode === 'none' && (
            <>
              <h2 className="mt-4 text-headline tracking-[-0.26px] font-[600] text-ink">
                Continue with email
              </h2>
              <p className="mt-3 text-body-sm text-text-secondary">
                We&rsquo;ll send a magic link to your inbox.
              </p>

              <form onSubmit={handleSubmit} className="mt-10">
                <label className="block">
                  <Eyebrow className="mb-3 block text-text-secondary">Email address</Eyebrow>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    required
                    autoFocus
                    className="w-full bg-surface-soft text-ink placeholder:text-text-muted rounded-sm border border-hairline-soft px-4 py-3 text-body-sm outline-none transition-shadow focus:border-accent-cobalt focus:shadow-focus-ring"
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
                  className="mt-8 w-full rounded-pill bg-gradient-brand text-white shadow-glow-nebula text-btn px-6 py-3 active:scale-[0.98] whitespace-nowrap disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {loading ? 'Signing in…' : 'Continue'}
                </motion.button>
              </form>

              <p className="mt-12 text-body-sm text-text-muted">
                New here? An account will be created automatically.
              </p>
            </>
          )}
        </motion.div>
      </main>
    </div>
  );
}
