import type { ComputeSession } from "@/features/studio/types";
import { SlotStatusRow } from "@/features/compute/slot-status-row";

export function ComputeSessionPanel({ session }: { session: ComputeSession }) {
  return (
    <div className="space-y-2">
      {(session.slots ?? []).map((slot) => (
        <SlotStatusRow key={slot.id} slot={slot} />
      ))}
    </div>
  );
}
