import { useEffect, useState } from "react";
import { apiFetch } from "../../auth/apiClient";
import { useAuth } from "../../auth/AuthProvider";

type Tenant = { id: string; slug: string; name: string };

export function TenantsPage() {
  const { me } = useAuth();
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    const r = await apiFetch("/api/admin/tenants");
    if (r.ok) setTenants(await r.json());
  }
  useEffect(() => {
    load();
  }, []);

  if (!me?.is_platform_admin) {
    return <div className="p-4">Platform admin access required.</div>;
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    const r = await apiFetch("/api/admin/tenants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug, name }),
    });
    if (!r.ok) {
      setErr(await r.text());
      return;
    }
    setSlug("");
    setName("");
    load();
  }

  async function remove(s: string) {
    if (!confirm(`Delete tenant ${s}?`)) return;
    const r = await apiFetch(`/api/admin/tenants/${s}`, { method: "DELETE" });
    if (!r.ok) setErr(await r.text());
    load();
  }

  return (
    <div className="p-6 max-w-3xl">
      <h1 className="text-xl font-semibold mb-4">Tenants</h1>
      <form onSubmit={create} className="flex gap-2 mb-4">
        <input
          className="border rounded px-2 py-1"
          placeholder="slug (lowercase)"
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
        />
        <input
          className="border rounded px-2 py-1 flex-1"
          placeholder="Display name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button type="submit" className="border rounded px-3 py-1">
          Create
        </button>
      </form>
      {err && <div className="text-red-600 mb-3">{err}</div>}
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left border-b">
            <th>Slug</th>
            <th>Name</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {tenants.map((t) => (
            <tr key={t.id} className="border-b">
              <td>{t.slug}</td>
              <td>{t.name}</td>
              <td className="text-right">
                <button onClick={() => remove(t.slug)} className="text-red-600">
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
