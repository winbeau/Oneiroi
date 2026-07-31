from pathlib import Path


class ArtifactWriter:
    def __init__(self, storage_root: Path) -> None:
        self.storage_root = storage_root.resolve()

    def prepare_job(self, job_id: str) -> tuple[Path, Path, Path]:
        if not job_id or any(part in {"..", "."} for part in Path(job_id).parts):
            raise ValueError("invalid job id")
        job_root = (self.storage_root / job_id).resolve()
        if not job_root.is_relative_to(self.storage_root):
            raise ValueError("job directory escaped storage root")
        output = job_root / "output" / "result.mp4"
        manifest = job_root / "manifest.json"
        cancel = job_root / "control" / "cancel_requested"
        output.parent.mkdir(parents=True, exist_ok=True)
        cancel.parent.mkdir(parents=True, exist_ok=True)
        return output, manifest, cancel
