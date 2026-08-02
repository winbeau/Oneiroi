import { useComputeSession, useComputeSessionEvents } from "@/features/compute/hooks";

export function ComputeSessionSync() {
  const session = useComputeSession().data;
  useComputeSessionEvents(session);
  return null;
}
