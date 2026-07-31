from collections.abc import Callable

EventSink = Callable[[dict[str, object]], None]


class EventReporter:
    def __init__(self, sink: EventSink) -> None:
        self.sink = sink

    def progress(
        self,
        job_id: str,
        phase: str,
        progress: int,
        details: dict[str, object],
    ) -> None:
        self.sink(
            {
                "type": "progress",
                "jobId": job_id,
                "phase": phase,
                "progress": progress,
                "details": details,
            }
        )
