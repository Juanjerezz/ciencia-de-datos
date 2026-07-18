"""Orquesta el pipeline medallion completo: bronze -> silver -> gold."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bronze.bronze_etl import run as run_bronze
from silver.silver_etl import run as run_silver
from gold.gold_etl import run as run_gold


def main() -> None:
    print("=== BRONZE ===")
    run_bronze()
    print("\n=== SILVER ===")
    run_silver()
    print("\n=== GOLD ===")
    run_gold()
    print("\nPipeline completo.")


if __name__ == "__main__":
    main()
