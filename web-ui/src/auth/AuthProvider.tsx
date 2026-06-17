// web-ui/src/auth/AuthProvider.tsx
import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { User } from "oidc-client-ts";
import { userManager, login } from "./oidc";
import { useTenantStore } from "../stores/tenantStore";
import { apiFetch } from "./apiClient";

type Me = {
  user_id: number;
  email: string | null;
  username: string;
  active_tenant: string;
  active_role: string;
  is_platform_admin: boolean;
  tenants: { slug: string }[];
};

type AuthCtx = {
  user: User | null;
  me: Me | null;
  loading: boolean;
};

const Ctx = createContext<AuthCtx>({ user: null, me: null, loading: true });
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const setTenants = useTenantStore((s) => s.setTenants);
  const setActive = useTenantStore((s) => s.setActive);
  const active = useTenantStore((s) => s.active);

  useEffect(() => {
    async function init() {
      // Handle the callback URL
      if (window.location.pathname === "/auth/callback") {
        await userManager.signinRedirectCallback();
        window.history.replaceState({}, "", "/");
      }
      const u = await userManager.getUser();
      if (!u || u.expired) {
        await login();
        return;
      }
      setUser(u);

      // Bootstrap tenant selection. /api/me needs X-Atria-Tenant — pick any group claim.
      let tenant = active;
      if (!tenant) {
        const groups: string[] = (u.profile as { groups?: string[] }).groups ?? [];
        const slugs = groups
          .map((g) => g.match(/^\/tenants\/([^/]+)$/)?.[1])
          .filter((s): s is string => !!s);
        if (slugs.length) {
          setActive(slugs[0]);
          tenant = slugs[0];
        }
      }
      if (tenant) {
        const r = await apiFetch("/api/me");
        if (r.ok) {
          const body = (await r.json()) as Me;
          setMe(body);
          setTenants(body.tenants);
        }
      }
      setLoading(false);
    }
    init();
  }, []);

  return <Ctx.Provider value={{ user, me, loading }}>{children}</Ctx.Provider>;
}
