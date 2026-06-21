"""Inicializa o banco SQLite (cria pastas + tabelas).

Rode UMA vez antes do primeiro pipeline:
    python scripts/setup_db.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Permite rodar `python scripts/setup_db.py` mesmo sem instalar como pacote
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import DB_PATH, get_conn, init_schema


def main() -> None:
    conn = get_conn()
    init_schema(conn)
    conn.close()
    print(f"[OK] Schema inicializado em {DB_PATH}")


if __name__ == "__main__":
    main()
