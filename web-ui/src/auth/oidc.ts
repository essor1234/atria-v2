// web-ui/src/auth/oidc.ts
import { UserManager, WebStorageStateStore, User } from "oidc-client-ts";

const KEYCLOAK_URL = import.meta.env.VITE_KEYCLOAK_URL ?? "http://localhost:8082";
const REALM = import.meta.env.VITE_KEYCLOAK_REALM ?? "atria";
const CLIENT_ID = import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "atria-web";

export const userManager = new UserManager({
  authority: `${KEYCLOAK_URL}/realms/${REALM}`,
  client_id: CLIENT_ID,
  redirect_uri: `${window.location.origin}/auth/callback`,
  post_logout_redirect_uri: window.location.origin,
  response_type: "code",
  scope: "openid profile email",
  userStore: new WebStorageStateStore({ store: window.localStorage }),
  automaticSilentRenew: true,
});

export async function login() {
  await userManager.signinRedirect();
}

export async function logout() {
  await userManager.signoutRedirect();
}

export async function getCurrentUser(): Promise<User | null> {
  return userManager.getUser();
}
