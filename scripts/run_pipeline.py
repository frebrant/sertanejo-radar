"""Entry point do pipeline (usado pelo GitHub Actions e manualmente).

Uso:
    python scripts/run_pipeline.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.pipeline import run  # noqa: E402


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    try:
        stats = run()
        print("\n=== Resumo ===")
        print(stats)
        return 0
    except Exception as exc:  # noqa: BLE001
        logging.exception("Pipeline falhou: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
