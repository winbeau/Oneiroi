import { useEffect } from "react";

import { useComputeSession, useComputeSessionEvents } from "@/features/compute/hooks";
import { useComputeUiStore } from "@/store/compute-ui-store";

export function ComputeSessionSync() {
  const session = useComputeSession().data;
  useComputeSessionEvents(session);

  useEffect(() => {
    const syncSession = (event: StorageEvent) => {
      if (event.key === "oneiroi-compute-ui-v1") {
        void useComputeUiStore.persist.rehydrate();
      }
    };
    window.addEventListener("storage", syncSession);
    return () => window.removeEventListener("storage", syncSession);
  }, []);

  return null;
}
