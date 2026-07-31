from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from oneiroi_common.compute import PipelineSpec
from oneiroi_common.generation import InternalI2VRequest

ProgressCallback = Callable[[str, int, dict[str, object]], None]
CancelCheck = Callable[[], bool]


class PipelineAdapter(Protocol):
    load_count: int

    def load(self, spec: PipelineSpec) -> None: ...

    def warm_up(self) -> None: ...

    def generate(
        self,
        request: InternalI2VRequest,
        output_path: Path,
        progress: ProgressCallback,
        is_cancelled: CancelCheck,
    ) -> dict[str, object]: ...

    def close(self) -> None: ...
