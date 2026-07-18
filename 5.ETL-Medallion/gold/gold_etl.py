"""
Capa Gold: modelado dimensional (esquema estrella) sobre silver.

Grano del hecho: un registro por evento operativo (Asset_ID + Timestamp).

Dimensiones:
- dim_tiempo: atributos de calendario derivados de Timestamp.
- dim_activo: activos logisticos (camiones), por Asset_ID.
- dim_estado_envio: valores unicos de Shipment_Status.
- dim_trafico: valores unicos de Traffic_Status.
- dim_demora: combinacion Logistics_Delay + Logistics_Delay_Reason.

Hecho:
- fact_envio_evento: claves foraneas a las dimensiones + metricas
  (Latitude, Longitude, Inventory_Level, Temperature, Humidity, Waiting_Time,
  User_Transaction_Amount, User_Purchase_Frequency, Asset_Utilization,
  Demand_Forecast).
"""
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
SILVER_DIR = BASE_DIR / "silver" / "data"
GOLD_DIR = BASE_DIR / "gold" / "data"

MEASURE_COLUMNS = [
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


def load_silver() -> pd.DataFrame:
    silver_path = SILVER_DIR / "silver_smart_logistics.parquet"
    if not silver_path.exists():
        raise FileNotFoundError(f"No existe {silver_path}. Corre silver_etl.py primero.")
    return pd.read_parquet(silver_path)


# Armo la dimension tiempo sacando los timestamps unicos de silver y les
# genero una clave subrogada correlativa (time_id) en vez de usar el
# Timestamp como PK. De paso derivo los atributos de calendario (año, mes,
# dia, hora, dia de semana, si es fin de semana) para no tener que calcularlos
# despues en cada consulta analitica.
def build_dim_tiempo(df: pd.DataFrame) -> pd.DataFrame:
    dim = df[["Timestamp"]].drop_duplicates().dropna().reset_index(drop=True)
    dim.insert(0, "time_id", range(1, len(dim) + 1))
    dim["date"] = dim["Timestamp"].dt.date
    dim["year"] = dim["Timestamp"].dt.year
    dim["month"] = dim["Timestamp"].dt.month
    dim["day"] = dim["Timestamp"].dt.day
    dim["hour"] = dim["Timestamp"].dt.hour
    dim["weekday"] = dim["Timestamp"].dt.day_name()
    dim["is_weekend"] = dim["Timestamp"].dt.weekday >= 5
    return dim


# Mismo criterio que dim_tiempo pero para los activos (camiones): la lista
# de Asset_ID unicos, con su propia clave subrogada.
def build_dim_activo(df: pd.DataFrame) -> pd.DataFrame:
    dim = df[["Asset_ID"]].drop_duplicates().dropna().reset_index(drop=True)
    dim.insert(0, "asset_key", range(1, len(dim) + 1))
    return dim


# Esta es generica porque Shipment_Status y Traffic_Status son ambas
# columnas categoricas de baja cardinalidad que se resuelven igual: junto
# los valores unicos y les pongo una clave. La reuso para las dos en vez de
# copiar y pegar la misma logica dos veces.
def build_dim_lookup(df: pd.DataFrame, column: str, key_name: str) -> pd.DataFrame:
    dim = df[[column]].drop_duplicates().dropna().reset_index(drop=True)
    dim.insert(0, key_name, range(1, len(dim) + 1))
    return dim


# dim_demora es un poco distinta: la combino a partir de dos columnas juntas
# (Logistics_Delay + Logistics_Delay_Reason), porque lo que quiero modelar
# es la combinacion "hubo demora / motivo" como una unica entidad, no cada
# columna por separado.
def build_dim_demora(df: pd.DataFrame) -> pd.DataFrame:
    dim = (
        df[["Logistics_Delay", "Logistics_Delay_Reason"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    dim.insert(0, "delay_key", range(1, len(dim) + 1))
    return dim


# Ac es donde se arma el hecho: parto de silver (grano evento) y le pego,
# con un merge por cada dimension, la clave subrogada correspondiente en vez
# del valor de texto original. Al final me quedo solo con las claves foraneas
# y las metricas -las columnas descriptivas ya quedaron resueltas en las
# dimensiones, no hace falta repetirlas ac.
def build_fact(
    df: pd.DataFrame,
    dim_tiempo: pd.DataFrame,
    dim_activo: pd.DataFrame,
    dim_estado_envio: pd.DataFrame,
    dim_trafico: pd.DataFrame,
    dim_demora: pd.DataFrame,
) -> pd.DataFrame:
    fact = df.merge(dim_tiempo[["time_id", "Timestamp"]], on="Timestamp", how="left")
    fact = fact.merge(dim_activo, on="Asset_ID", how="left")
    fact = fact.merge(dim_estado_envio, on="Shipment_Status", how="left")
    fact = fact.merge(dim_trafico, on="Traffic_Status", how="left")
    fact = fact.merge(
        dim_demora, on=["Logistics_Delay", "Logistics_Delay_Reason"], how="left"
    )

    key_columns = [
        "_row_id",
        "time_id",
        "asset_key",
        "shipment_status_key",
        "traffic_status_key",
        "delay_key",
    ]
    return fact[key_columns + MEASURE_COLUMNS]


# Orquesta la capa: construyo primero todas las dimensiones, despues el
# hecho (que depende de tenerlas ya armadas para poder hacer los merges), y
# guardo las seis tablas del esquema estrella como parquet separados.
def run() -> None:
    GOLD_DIR.mkdir(parents=True, exist_ok=True)

    df = load_silver()

    dim_tiempo = build_dim_tiempo(df)
    dim_activo = build_dim_activo(df)
    dim_estado_envio = build_dim_lookup(df, "Shipment_Status", "shipment_status_key")
    dim_trafico = build_dim_lookup(df, "Traffic_Status", "traffic_status_key")
    dim_demora = build_dim_demora(df)

    fact_envio_evento = build_fact(
        df, dim_tiempo, dim_activo, dim_estado_envio, dim_trafico, dim_demora
    )

    tables = {
        "dim_tiempo": dim_tiempo,
        "dim_activo": dim_activo,
        "dim_estado_envio": dim_estado_envio,
        "dim_trafico": dim_trafico,
        "dim_demora": dim_demora,
        "fact_envio_evento": fact_envio_evento,
    }

    for name, table in tables.items():
        output_path = GOLD_DIR / f"{name}.parquet"
        table.to_parquet(output_path, index=False)
        print(f"[gold] {name}: {len(table)} filas -> {output_path}")


if __name__ == "__main__":
    run()
