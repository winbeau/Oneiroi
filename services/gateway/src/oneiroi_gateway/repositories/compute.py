from datetime import datetime
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from oneiroi_common.compute import ComputeSessionSnapshot, ComputeSessionState, ComputeSlot
from oneiroi_gateway.db.models.studio import ComputeSessionModel, GpuSlotModel


class ComputeStateRepository(Protocol):
    async def save(self, snapshot: ComputeSessionSnapshot) -> None: ...

    async def load_active(self) -> list[ComputeSessionSnapshot]: ...


class InMemoryComputeStateRepository:
    def __init__(self) -> None:
        self.items: dict[str, ComputeSessionSnapshot] = {}

    async def save(self, snapshot: ComputeSessionSnapshot) -> None:
        self.items[snapshot.id] = snapshot.model_copy(deep=True)

    async def load_active(self) -> list[ComputeSessionSnapshot]:
        return [
            item.model_copy(deep=True)
            for item in self.items.values()
            if item.state is not ComputeSessionState.RELEASED
        ]


class SqlComputeStateRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def save(self, snapshot: ComputeSessionSnapshot) -> None:
        async with self.sessions() as session:
            row = await session.get(ComputeSessionModel, snapshot.id)
            values = {
                "owner_id": snapshot.owner_id,
                "state": snapshot.state.value,
                "requested_gpu_count": snapshot.requested_gpu_count,
                "allocated_gpu_count": snapshot.allocated_gpu_count,
                "selection_mode": snapshot.selection_mode.value,
                "profile_policy": snapshot.profile_policy.value,
                "allow_partial": snapshot.allow_partial,
                "profile_plan_json": snapshot.profile_plan.model_dump(
                    mode="json", by_alias=True
                ),
                "created_at": datetime.fromisoformat(snapshot.created_at),
                "ready_at": (
                    datetime.fromisoformat(snapshot.ready_at) if snapshot.ready_at else None
                ),
                "released_at": (
                    datetime.fromisoformat(snapshot.released_at)
                    if snapshot.released_at
                    else None
                ),
                "error_code": snapshot.error_code,
                "error_message": snapshot.error_message,
            }
            if row is None:
                row = ComputeSessionModel(id=snapshot.id, **values)
                session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            gpu_ids = [slot.gpu_id for slot in snapshot.slots]
            await session.execute(
                delete(GpuSlotModel).where(
                    (GpuSlotModel.compute_session_id == snapshot.id)
                    | (GpuSlotModel.gpu_uuid.in_(gpu_ids))
                )
            )
            session.add_all(
                [
                    GpuSlotModel(
                        id=slot.id,
                        gpu_uuid=slot.gpu_id,
                        physical_index=slot.physical_index,
                        state=slot.state.value,
                        profile_id=slot.profile.value if slot.profile else None,
                        pipeline_spec_hash=slot.pipeline_spec_hash,
                        compute_session_id=snapshot.id,
                        vram_total_mib=0,
                        vram_used_mib=0,
                        last_error=slot.last_error,
                    )
                    for slot in snapshot.slots
                ]
            )
            await session.commit()

    async def load_active(self) -> list[ComputeSessionSnapshot]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(ComputeSessionModel).where(
                        ComputeSessionModel.state != ComputeSessionState.RELEASED.value
                    )
                )
            ).all()
            result: list[ComputeSessionSnapshot] = []
            for row in rows:
                slots = (
                    await session.scalars(
                        select(GpuSlotModel).where(
                            GpuSlotModel.compute_session_id == row.id
                        )
                    )
                ).all()
                result.append(
                    ComputeSessionSnapshot(
                        id=row.id,
                        ownerId=row.owner_id,
                        state=row.state,
                        requestedGpuCount=row.requested_gpu_count,
                        allocatedGpuCount=row.allocated_gpu_count,
                        selectionMode=row.selection_mode,
                        profilePolicy=row.profile_policy,
                        allowPartial=row.allow_partial,
                        profilePlan=row.profile_plan_json,
                        slots=[
                            ComputeSlot(
                                id=slot.id,
                                gpuId=slot.gpu_uuid,
                                physicalIndex=slot.physical_index,
                                state=slot.state,
                                profile=slot.profile_id,
                                pipelineSpecHash=slot.pipeline_spec_hash,
                                lastError=slot.last_error,
                            )
                            for slot in slots
                        ],
                        errorCode=row.error_code,
                        errorMessage=row.error_message,
                        createdAt=row.created_at.isoformat(),
                        readyAt=row.ready_at.isoformat() if row.ready_at else None,
                        releasedAt=row.released_at.isoformat() if row.released_at else None,
                    )
                )
        return result
