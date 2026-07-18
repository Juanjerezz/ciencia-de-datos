# ETL Medallion — Smart Logistics Supply Chain Dataset

Pipeline de práctica (arquitectura medallion: bronze / silver / gold) sobre el
[Smart Logistics Supply Chain Dataset](https://www.kaggle.com/datasets/ziya07/smart-logistics-supply-chain-dataset)
(Kaggle, autor `ziya07`).

Granularidad del dataset: un evento operativo por activo (camión) y timestamp.

## Setup

```bash
pip install -r requirements.txt
```

Descargar el CSV desde Kaggle y colocarlo en `data/raw/` (cualquier nombre `.csv`,
el pipeline toma el primero que encuentre).

## Estructura

```
data/raw/           CSV fuente descargado de Kaggle (no versionado)
bronze/
  bronze_etl.py      Ingesta 1:1 + metadata técnica
  data/               bronze_smart_logistics.parquet
silver/
  silver_etl.py       Tipado, deduplicación, reglas de calidad
  data/               silver_smart_logistics.parquet, dq_report.csv
gold/
  gold_etl.py          Modelado dimensional (esquema estrella)
  data/               dim_tiempo, dim_activo, dim_estado_envio, dim_trafico,
                       dim_demora, fact_envio_evento (parquet)
run_pipeline.py     Corre bronze -> silver -> gold en orden
```

## Uso

```bash
python run_pipeline.py
```

O capa por capa:

```bash
python bronze/bronze_etl.py
python silver/silver_etl.py
python gold/gold_etl.py
```

## Decisiones de diseño

### Bronze
Copia cruda del CSV sin transformar valores, agregando `_row_id`, `_source_file`
y `_ingested_at` para trazabilidad.

### Silver
- `Timestamp` se convierte a `datetime`; `Logistics_Delay` (viene como `0`/`1`
  en el CSV real) se convierte a `bool`.
- Deduplicación por `(Asset_ID, Timestamp)`.
- Chequeo de calidad (no corrección forzada): se esperaría que si
  `Logistics_Delay == False`, `Logistics_Delay_Reason` sea nulo. **En los
  datos reales esto no se cumple**: ~318 de 434 filas sin demora igual tienen
  un motivo cargado, lo que sugiere que el campo no es exclusivo de demoras
  confirmadas (podría ser un motivo de riesgo/pronóstico). Por eso no se
  sobreescribe el dato; solo se cuentan los casos en
  `_dq_delay_reason_mismatch` y en el reporte de calidad.
- Outliers en columnas numéricas (incluye `Latitude`/`Longitude`) detectados
  por IQR y marcados en columnas `_dq_outlier_<columna>`, sin eliminar filas.
- `silver/data/dq_report.csv` resume nulls, duplicados, inconsistencias y
  outliers detectados.

### Gold
Esquema estrella con grano **un registro por `Asset_ID` + `Timestamp`**:

- **dim_tiempo**: atributos de calendario derivados de `Timestamp`.
- **dim_activo**: activos logísticos (`Asset_ID`).
- **dim_estado_envio**: valores de `Shipment_Status`.
- **dim_trafico**: valores de `Traffic_Status`.
- **dim_demora**: combinación `Logistics_Delay` + `Logistics_Delay_Reason`.
- **fact_envio_evento**: claves foráneas a las dimensiones + métricas
  (`Latitude`, `Longitude`, `Inventory_Level`, `Temperature`, `Humidity`,
  `Waiting_Time`, `User_Transaction_Amount`, `User_Purchase_Frequency`,
  `Asset_Utilization`, `Demand_Forecast`).

## Diagrama del modelo estrella (gold)

![Modelo estrella](docs/star_schema.svg)

## Dashboard en Power BI

Guía paso a paso (conexión a los parquet de gold, relaciones, medidas DAX y
layout sugerido) en [`docs/powerbi_guide.md`](docs/powerbi_guide.md).

## Por qué estas decisiones (resumen)

- **Parquet en vez de CSV para bronze/silver/gold**: formato columnar orientado
  a OLAP — comprime mejor, tipa las columnas (a diferencia del CSV) y permite
  leer solo las columnas necesarias en vez de la fila completa, que es el
  patrón típico de consultas analíticas de este proyecto.
- **Un script por capa, no notebooks**: cada capa es una función `run()`
  reproducible y encadenable (`run_pipeline.py`), en vez de celdas que
  dependen del orden de ejecución manual.
- **Metadata técnica en bronze (`_row_id`, `_source_file`, `_ingested_at`)**:
  trazabilidad de dónde vino cada fila sin tocar el dato original — bronze
  debe poder reconstruirse igual al CSV fuente.
- **Silver no borra ni "corrige" datos dudosos, los marca** (`_dq_outlier_*`,
  `_dq_delay_reason_mismatch`): el objetivo de esta capa es dejar el dato
  tipado y confiable, pero decidir qué hacer con outliers/inconsistencias es
  una decisión de análisis, no del ETL. Se prefirió no perder información.
- **Claves subrogadas (surrogate keys) en gold** (`asset_key`, `time_id`,
  etc.) en vez de usar los IDs de negocio como PK: es la práctica estándar en
  modelado dimensional, desacopla el modelo de cambios en el ID de origen y
  es requisito para escalar a slowly changing dimensions más adelante.
- **Grano del hecho = evento (`Asset_ID` + `Timestamp`)**: es el nivel de
  detalle real del dataset (no hay "pedidos" ni "líneas"), así que agregar a
  un grano mayor implicaría perder información en la capa gold.

## Resultados de la última corrida

Sobre el dataset real (1000 filas, 10 activos):

| Capa   | Resultado |
|--------|-----------|
| Bronze | 1000 filas ingeridas tal cual desde el CSV |
| Silver | 1000 filas resultantes · 0 duplicados · 0 timestamps inválidos · 0 outliers (IQR) · 318 filas marcadas por `_dq_delay_reason_mismatch` (reportadas, no corregidas) |
| Gold   | `dim_tiempo`: 1000 · `dim_activo`: 10 · `dim_estado_envio`: 3 · `dim_trafico`: 3 · `dim_demora`: 8 · `fact_envio_evento`: 1000 filas, sin nulls en ninguna clave foránea |
