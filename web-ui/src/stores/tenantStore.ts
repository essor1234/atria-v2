// web-ui/src/stores/tenantStore.ts
import { create } from "zustand";

type Tenant = { slug: string };

type TenantState = {
  active: string | null;
  tenants: Tenant[];
  setActive: (slug: string) => void;
  setTenants: (tenants: Tenant[]) => void;
};

const STORAGE_KEY = "atria.activeTenant";

export const useTenantStore = create<TenantState>((set) => ({
  active: localStorage.getItem(STORAGE_KEY),
  tenants: [],
  setActive: (slug) => {
    localStorage.setItem(STORAGE_KEY, slug);
    set({ active: slug });
  },
  setTenants: (tenants) => set({ tenants }),
}));
