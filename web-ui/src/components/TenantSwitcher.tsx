// web-ui/src/components/TenantSwitcher.tsx
import { useAuth } from "../auth/AuthProvider";
import { useTenantStore } from "../stores/tenantStore";

export function TenantSwitcher() {
  const { me } = useAuth();
  const active = useTenantStore((s) => s.active);
  const setActive = useTenantStore((s) => s.setActive);
  if (!me || me.tenants.length === 0) return null;

  return (
    <select
      value={active ?? ""}
      onChange={(e) => {
        setActive(e.target.value);
        window.location.reload(); // simplest way to re-resolve principal/tenant scope
      }}
      className="text-sm border rounded px-2 py-1"
    >
      {me.tenants.map((t) => (
        <option key={t.slug} value={t.slug}>
          {t.slug}
        </option>
      ))}
    </select>
  );
}
