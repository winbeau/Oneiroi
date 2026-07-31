import { create } from "zustand";

type WorkspaceState = {
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;
};

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  sidebarOpen:
    typeof window === "undefined"
      ? true
      : window.matchMedia("(min-width: 768px)").matches,
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
}));
