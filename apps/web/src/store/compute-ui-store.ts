import { create } from "zustand";
import { persist } from "zustand/middleware";

type ComputeUiState = {
  activeSessionId: string;
  setActiveSessionId: (id: string) => void;
  clearActiveSession: () => void;
};

export const useComputeUiStore = create<ComputeUiState>()(
  persist(
    (set) => ({
      activeSessionId: "",
      setActiveSessionId: (activeSessionId) => set({ activeSessionId }),
      clearActiveSession: () => set({ activeSessionId: "" }),
    }),
    { name: "oneiroi-compute-ui-v1" },
  ),
);
