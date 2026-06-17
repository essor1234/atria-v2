import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { apiFetch } from "@/auth/apiClient";
import { useAuth } from "@/auth/AuthProvider";

type TenantUser = { user_id: string; username: string; email: string; role: string };

export function TenantUsersPage() {
  const { slug = "" } = useParams();
  const { me } = useAuth();
  const [users, setUsers] = useState<TenantUser[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"admin" | "member">("member");
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    const r = await apiFetch(`/api/admin/tenants/${slug}/users`);
    if (r.ok) setUsers(await r.json());
    else setErr(await r.text());
  }
  useEffect(() => {
    load();
  }, [slug]);

  const canAdmin = me?.is_platform_admin || (me?.active_tenant === slug && me?.active_role === "admin");
  if (!canAdmin) return <div className="p-4">Tenant admin access required.</div>;

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    const r = await apiFetch(`/api/admin/tenants/${slug}/invites`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
    });
    if (!r.ok) {
      setErr(await r.text());
      return;
    }
    setInviteEmail("");
    load();
  }

  async function changeRole(user_id: string, role: "admin" | "member") {
    const r = await apiFetch(`/api/admin/tenants/${slug}/users/${user_id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
    if (!r.ok) setErr(await r.text());
    load();
  }

  async function remove(user_id: string) {
    if (!confirm("Remove user from tenant?")) return;
    const r = await apiFetch(`/api/admin/tenants/${slug}/users/${user_id}`, { method: "DELETE" });
    if (!r.ok) setErr(await r.text());
    load();
  }

  return (
    <div className="p-6 max-w-3xl">
      <h1 className="text-xl font-semibold mb-4">{slug} — users</h1>
      <form onSubmit={invite} className="flex gap-2 mb-4">
        <input
          className="border rounded px-2 py-1 flex-1"
          placeholder="email@example.com"
          value={inviteEmail}
          onChange={(e) => setInviteEmail(e.target.value)}
        />
        <select
          className="border rounded px-2 py-1"
          value={inviteRole}
          onChange={(e) => setInviteRole(e.target.value as "admin" | "member")}
        >
          <option value="member">member</option>
          <option value="admin">admin</option>
        </select>
        <button type="submit" className="border rounded px-3 py-1">
          Invite
        </button>
      </form>
      {err && <div className="text-red-600 mb-3">{err}</div>}
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left border-b">
            <th>User</th>
            <th>Email</th>
            <th>Role</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.user_id} className="border-b">
              <td>{u.username}</td>
              <td>{u.email}</td>
              <td>
                <select
                  value={u.role}
                  onChange={(e) => changeRole(u.user_id, e.target.value as "admin" | "member")}
                >
                  <option value="member">member</option>
                  <option value="admin">admin</option>
                </select>
              </td>
              <td className="text-right">
                <button onClick={() => remove(u.user_id)} className="text-red-600">
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
