"""
Capa Bronze: ingesta cruda del CSV fuente sin transformar el contenido.
Agrega solo metadata tecnica de trazabilidad (_ingested_at, _source_file, _row_id).
"""
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
BRONZE_DIR = BASE_DIR / "bronze" / "data"


# Busco el CSV en data/raw sin asumir un nombre fijo, total en esta capa
# solo me importa que exista *algun* archivo para ingerir. Si no hay nada,
# corto la ejecucion con un mensaje claro en vez de un error de pandas confuso.
def find_source_csv() -> Path:
    csv_files = sorted(RAW_DIR.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(
            f"No se encontro ningun CSV en {RAW_DIR}. "
            "Descarga el dataset de Kaggle (ziya07/smart-logistics-supply-chain-dataset) "
            "y coloca el archivo .csv en esa carpeta."
        )
    return csv_files[0]


# Esta es la ingesta en si: leo el CSV tal cual viene, sin tocar ningun valor
# (esa es la idea de bronze, una copia fiel de la fuente). Lo unico que agrego
# es metadata de trazabilidad -de donde salio cada fila y cuando la cargue-
# para poder auditar el pipeline despues. Guardo en parquet porque las
# siguientes capas lo van a leer varias veces y conviene tenerlo ya tipado
# y comprimido en vez de re-parsear un CSV cada vez.
def run() -> Path:
    BRONZE_DIR.mkdir(parents=True, exist_ok=True)
    source_path = find_source_csv()

    df = pd.read_csv(source_path)

    ingested_at = datetime.now(timezone.utc).isoformat()
    df.insert(0, "_row_id", range(1, len(df) + 1))
    df["_source_file"] = source_path.name
    df["_ingested_at"] = ingested_at

    output_path = BRONZE_DIR / "bronze_smart_logistics.parquet"
    df.to_parquet(output_path, index=False)

    print(f"[bronze] Fuente: {source_path}")
    print(f"[bronze] Filas ingeridas: {len(df)}")
    print(f"[bronze] Guardado en: {output_path}")
    return output_path


if __name__ == "__main__":
    run()
