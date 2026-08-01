import asyncio
from dataclasses import dataclass

from oneiroi_common.compute import ComputeSlot, GpuState, ProfileTier
from oneiroi_gateway.services.compute_sessions import ComputeSessionService


@dataclass(frozen=True, slots=True)
class SlotReservation:
    session_id: str
    slot_id: str
    gpu_id: str
    physical_index: int
    profile: ProfileTier
    fencing_token: str


class JobScheduler:
    def __init__(self, sessions: ComputeSessionService) -> None:
        self.sessions = sessions
        self._busy_slots: set[str] = set()
        self._lock = asyncio.Lock()

    async def reserve(
        self,
        owner_id: str,
        session_id: str,
        profile: ProfileTier,
    ) -> SlotReservation:
        session = self.sessions.get(owner_id, session_id)
        self.sessions.touch(session_id)
        async with self._lock:
            candidates = sorted(
                [
                    slot
                    for slot in session.slots
                    if slot.profile is profile
                    and slot.state is GpuState.READY
                    and slot.id not in self._busy_slots
                ],
                key=lambda slot: (slot.physical_index, slot.gpu_id),
            )
            if not candidates:
                code = "HQ_NOT_READY" if profile is ProfileTier.HQ else "COMPUTE_NOT_READY"
                raise RuntimeError(code)
            slot = candidates[0]
            self._busy_slots.add(slot.id)
            slot.state = GpuState.BUSY
            reservation = self._reservation(
                session.id,
                slot,
                profile,
                self.sessions.fencing_token(slot.id),
            )
        await self.sessions.persist(session.id)
        return reservation

    async def restore(self, reservation: SlotReservation) -> None:
        async with self._lock:
            self._busy_slots.add(reservation.slot_id)
            session = self.sessions.sessions.get(reservation.session_id)
            if session is None:
                raise RuntimeError("COMPUTE_SESSION_NOT_RESTORED")
            slot = next((item for item in session.slots if item.id == reservation.slot_id), None)
            if slot is None:
                raise RuntimeError("COMPUTE_SLOT_NOT_RESTORED")
            slot.state = GpuState.BUSY
        await self.sessions.persist(reservation.session_id)

    async def release(self, reservation: SlotReservation) -> None:
        self.sessions.touch(reservation.session_id)
        async with self._lock:
            self._busy_slots.discard(reservation.slot_id)
            session = self.sessions.sessions.get(reservation.session_id)
            if session is None:
                return
            slot = next((item for item in session.slots if item.id == reservation.slot_id), None)
            if slot is not None and slot.state is GpuState.BUSY:
                slot.state = GpuState.READY
        await self.sessions.persist(reservation.session_id)

    @staticmethod
    def _reservation(
        session_id: str,
        slot: ComputeSlot,
        profile: ProfileTier,
        fencing_token: str,
    ) -> SlotReservation:
        return SlotReservation(
            session_id=session_id,
            slot_id=slot.id,
            gpu_id=slot.gpu_id,
            physical_index=slot.physical_index,
            profile=profile,
            fencing_token=fencing_token,
        )
