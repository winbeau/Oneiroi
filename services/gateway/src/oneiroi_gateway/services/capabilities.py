from oneiroi_common.compute import (
    FAST_PROFILE_ID,
    HQ_PROFILE_ID,
    ComputeCapabilitiesResponse,
    ComputeSessionSnapshot,
    GpuState,
    ProfileCapability,
    ProfileTier,
)
from oneiroi_common.errors import ErrorCode, OneiroiError


class CapabilityService:
    def __init__(self, *, fast_installed: bool = True, hq_installed: bool = True) -> None:
        self.fast_installed = fast_installed
        self.hq_installed = hq_installed

    def get(self, session: ComputeSessionSnapshot | None = None) -> ComputeCapabilitiesResponse:
        fast_available = self.fast_installed
        fast_reason = None if self.fast_installed else "FAST_PROFILE_NOT_INSTALLED"
        hq_available = self.hq_installed
        hq_reason = None if self.hq_installed else "HQ_PROFILE_NOT_INSTALLED"

        if session is not None:
            ready_fast = any(
                slot.profile is ProfileTier.FAST and slot.state is GpuState.READY
                for slot in session.slots
            )
            ready_hq = any(
                slot.profile is ProfileTier.HQ and slot.state is GpuState.READY
                for slot in session.slots
            )
            fast_available = self.fast_installed and ready_fast
            if self.fast_installed and not ready_fast:
                fast_reason = "FAST_NOT_READY"
            if session.allocated_gpu_count < 2:
                hq_available = False
                hq_reason = ErrorCode.HQ_REQUIRES_AT_LEAST_2_GPUS.value
            elif self.hq_installed and not ready_hq:
                hq_available = False
                hq_reason = ErrorCode.HQ_NOT_READY.value
            else:
                hq_available = self.hq_installed and ready_hq

        return ComputeCapabilitiesResponse(
            profiles=[
                ProfileCapability(
                    id=FAST_PROFILE_ID,
                    tier=ProfileTier.FAST,
                    available=fast_available,
                    resolutions=["720p", "1080p"],
                    durations=[5, 8, 10],
                    unavailableReason=fast_reason,
                ),
                ProfileCapability(
                    id=HQ_PROFILE_ID,
                    tier=ProfileTier.HQ,
                    available=hq_available,
                    resolutions=["1080p"],
                    durations=[5],
                    unavailableReason=hq_reason,
                ),
            ]
        )

    def require_profile(
        self,
        session: ComputeSessionSnapshot,
        tier: ProfileTier,
    ) -> ProfileCapability:
        capability = next(profile for profile in self.get(session).profiles if profile.tier is tier)
        if capability.available:
            return capability
        reason = capability.unavailable_reason or "COMPUTE_NOT_READY"
        code = (
            ErrorCode(reason)
            if reason in {item.value for item in ErrorCode}
            else ErrorCode.COMPUTE_NOT_READY
        )
        raise OneiroiError(code, reason)
