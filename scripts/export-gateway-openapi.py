from __future__ import annotations

import json
from pathlib import Path

from oneiroi_gateway.main import create_app
from oneiroi_gateway.settings import GatewaySettings

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "apps" / "web" / "openapi" / "gateway.json"


def main() -> None:
    app = create_app(
        GatewaySettings(
            environment="development",
            persistence_enabled=False,
            redis_leases_enabled=False,
            redis_job_streams_enabled=False,
            nvml_inventory_enabled=False,
        )
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(OUTPUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
