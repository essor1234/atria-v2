// web-ui/src/auth/apiClient.ts
import { userManager } from "./oidc";
import { useTenantStore } from "../stores/tenantStore";

export async function apiFetch(input: RequestInfo, init: RequestInit = {}): Promise<Response> {
  const user = await userManager.getUser();
  const headers = new Headers(init.headers ?? {});
  if (user?.access_token) {
    headers.set("Authorization", `Bearer ${user.access_token}`);
  }
  const tenant = useTenantStore.getState().active;
  if (tenant) headers.set("X-Atria-Tenant", tenant);
  return fetch(input, { ...init, headers });
}
