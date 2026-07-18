"""
Capa Silver: limpieza, tipado y reglas de calidad de datos sobre bronze.

Transformaciones:
- Timestamp de texto a datetime.
- Logistics_Delay de int (0/1) a boolean.
- Deduplicacion por (Asset_ID, Timestamp), quedandose con el primer registro ingerido.
- Chequeo de calidad: se esperaria que Logistics_Delay_Reason sea nulo cuando
  Logistics_Delay es False. En los datos reales esto NO se cumple de forma
  consistente (hay filas sin demora que igual traen un motivo cargado), por lo
  que no se sobreescriben valores: solo se cuentan los casos que rompen la
  regla esperada en _dq_delay_reason_mismatch, a modo informativo.
- Deteccion de outliers en columnas numericas via rango intercuartilico (IQR),
  marcados en columnas _dq_outlier_<columna> sin eliminar filas.
- Reporte de calidad de datos (nulls, duplicados, outliers, inconsistencias) en silver/data/dq_report.csv.
"""
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
BRONZE_DIR = BASE_DIR / "bronze" / "data"
SILVER_DIR = BASE_DIR / "silver" / "data"

NUMERIC_COLUMNS = [
    "Latitude",
    "Longitude",
    "Inventory_Level",
    "Temperature",
    "Humidity",
    "Waiting_Time",
    "User_Transaction_Amount",
    "User_Purchase_Frequency",
    "Asset_Utilization",
    "Demand_Forecast",
]

CATEGORICAL_COLUMNS = [
    "Asset_ID",
    "Shipment_Status",
    "Traffic_Status",
    "Logistics_Delay_Reason",
]


# Simplemente traigo lo que dejo bronze. Si todavia no corrio bronze, aviso
# en vez de tirar un error críptico de "archivo no encontrado" de pandas.
def load_bronze() -> pd.DataFrame:
    bronze_path = BRONZE_DIR / "bronze_smart_logistics.parquet"
    if not bronze_path.exists():
        raise FileNotFoundError(f"No existe {bronze_path}. Corre bronze_etl.py primero.")
    return pd.read_parquet(bronze_path)


# En bronze todo llega como texto o con el tipo que Kaggle le puso al CSV.
# Ac lo paso a los tipos que realmente son: Timestamp a datetime para poder
# hacer operaciones de fecha despues, y Logistics_Delay (que viene 0/1) a
# booleano para que sea mas legible. Las categoricas las dejo como string
# "limpio" (sin espacios de mas) para que los merges de gold no fallen por
# un espacio invisible.
def convert_types(df: pd.DataFrame) -> pd.DataFrame:
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df["Logistics_Delay"] = df["Logistics_Delay"].astype(bool)
    for col in CATEGORICAL_COLUMNS:
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip()
    return df


# Un mismo activo no deberia tener dos eventos con el mismo timestamp, asi
# que si aparece duplicado me quedo con el que se ingirio primero (ordeno por
# _ingested_at antes de eliminar). Devuelvo tambien cuantas filas saque, para
# poder reportarlo despues.
def deduplicate(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    before = len(df)
    df = df.sort_values("_ingested_at").drop_duplicates(
        subset=["Asset_ID", "Timestamp"], keep="first"
    )
    duplicates_removed = before - len(df)
    return df, duplicates_removed


# La idea original era: "si no hubo demora, no deberia haber motivo de
# demora cargado". Cuando lo probe contra el dataset real, la regla se rompe
# en un monton de filas (no es un caso aislado), asi que asumo que el campo
# Logistics_Delay_Reason no es exclusivo de demoras confirmadas y decido NO
# pisar el dato. Solo dejo marcado que fila rompe la regla esperada, por si
# alguien despues quiere investigarlo en el analisis.
def check_delay_reason_rule(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    is_no_delay = ~df["Logistics_Delay"]
    has_reason = df["Logistics_Delay_Reason"].notna() & (
        df["Logistics_Delay_Reason"].str.len() > 0
    )
    mismatch_mask = is_no_delay & has_reason

    df["_dq_delay_reason_mismatch"] = mismatch_mask

    return df, int(mismatch_mask.sum())


# Para cada columna numerica calculo el rango intercuartilico (IQR) y marco
# como outlier todo lo que caiga fuera de 1.5 veces ese rango (el criterio
# clasico de boxplot). No elimino filas: solo agrego una columna booleana
# _dq_outlier_<col> para que quede a criterio de quien analice los datos
# despues decidir si son errores de carga o valores reales extremos.
def flag_outliers(df: pd.DataFrame) -> pd.DataFrame:
    for col in NUMERIC_COLUMNS:
        if col not in df.columns:
            continue
        q1, q3 = df[col].quantile([0.25, 0.75])
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        df[f"_dq_outlier_{col}"] = (df[col] < lower) | (df[col] > upper)
    return df


# Junto todos los chequeos de calidad que fui haciendo (duplicados,
# inconsistencias, nulls, outliers) en una sola tabla para poder mirarlos
# de un vistazo en dq_report.csv, sin tener que ir a buscarlos columna por
# columna en el parquet.
def build_dq_report(df: pd.DataFrame, duplicates_removed: int, delay_reason_mismatch: int) -> pd.DataFrame:
    rows = [
        {"check": "duplicates_removed", "count": duplicates_removed},
        {"check": "delay_reason_rule_mismatches", "count": delay_reason_mismatch},
        {"check": "timestamp_unparseable", "count": int(df["Timestamp"].isna().sum())},
    ]
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            rows.append({"check": f"nulls_{col}", "count": int(df[col].isna().sum())})
            rows.append({"check": f"outliers_{col}", "count": int(df[f"_dq_outlier_{col}"].sum())})
    for col in CATEGORICAL_COLUMNS:
        if col in df.columns:
            rows.append({"check": f"nulls_{col}", "count": int(df[col].isna().sum())})
    return pd.DataFrame(rows)


# Orquesta toda la capa: carga bronze, aplica las transformaciones en orden,
# arma el reporte de calidad y guarda todo. El orden importa un poco: dedupo
# antes de chequear la regla de demora para no contar dos veces la misma
# inconsistencia si habia una fila repetida.
def run() -> Path:
    SILVER_DIR.mkdir(parents=True, exist_ok=True)

    df = load_bronze()
    df = convert_types(df)
    df, duplicates_removed = deduplicate(df)
    df, delay_reason_mismatch = check_delay_reason_rule(df)
    df = flag_outliers(df)

    dq_report = build_dq_report(df, duplicates_removed, delay_reason_mismatch)
    dq_report_path = SILVER_DIR / "dq_report.csv"
    dq_report.to_csv(dq_report_path, index=False)

    output_path = SILVER_DIR / "silver_smart_logistics.parquet"
    df.to_parquet(output_path, index=False)

    print(f"[silver] Filas resultantes: {len(df)}")
    print(f"[silver] Duplicados eliminados: {duplicates_removed}")
    print(f"[silver] Filas que rompen regla Delay/Reason (no corregidas, solo reportadas): {delay_reason_mismatch}")
    print(f"[silver] Reporte de calidad: {dq_report_path}")
    print(f"[silver] Guardado en: {output_path}")
    return output_path


if __name__ == "__main__":
    run()
