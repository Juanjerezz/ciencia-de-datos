# Dashboard en Power BI — guía paso a paso

Esta guía arma un dashboard sobre la capa **gold** (`gold/data/*.parquet`), que
ya viene modelada en esquema estrella, así que en Power BI el trabajo es
básicamente: conectar, relacionar y visualizar.

Antes de empezar, corré `python run_pipeline.py` para tener los parquet
actualizados.

## 1. Conectar los datos

Power BI Desktop lee Parquet nativo desde hace un par de versiones (si tu
versión es vieja y no aparece la opción, actualizalo desde Microsoft Store).

1. `Inicio` → `Obtener datos` → buscar **Parquet**.
2. Repetí la importación **una vez por archivo**, apuntando a cada uno de:
   - `gold/data/dim_tiempo.parquet`
   - `gold/data/dim_activo.parquet`
   - `gold/data/dim_estado_envio.parquet`
   - `gold/data/dim_trafico.parquet`
   - `gold/data/dim_demora.parquet`
   - `gold/data/fact_envio_evento.parquet`
3. En cada uno, `Transformar datos` no hace falta tocarlo — ya vienen tipados
   desde Python. Directo a `Cerrar y aplicar`.

Alternativa más rápida: `Obtener datos` → **Carpeta** → seleccionar
`gold/data/` → `Combinar y transformar`. Ahí Power BI te va a mostrar los 6
archivos juntos; como cada uno tiene columnas distintas, es más prolijo
importarlos uno por uno como en el paso 2, así que salvo que ya le tengas
práctica al combinador, mejor uno por uno.

## 2. Armar las relaciones (vista Modelo)

Andá a la vista **Modelo** (ícono de la izquierda) y armá estas 5 relaciones
arrastrando de la clave del hecho a la clave de la dimensión. Todas son
**muchos a uno** (`fact_envio_evento` es el lado "muchos"), con dirección de
filtro única (de dimensión hacia hecho):

| Desde (fact_envio_evento) | Hacia (dimensión) |
|---|---|
| `time_id` | `dim_tiempo[time_id]` |
| `asset_key` | `dim_activo[asset_key]` |
| `shipment_status_key` | `dim_estado_envio[shipment_status_key]` |
| `traffic_status_key` | `dim_trafico[traffic_status_key]` |
| `delay_key` | `dim_demora[delay_key]` |

Te debería quedar el típico dibujo de estrella: `fact_envio_evento` en el
medio y las 5 dimensiones alrededor (el mismo layout que el diagrama en
[`docs/star_schema.svg`](star_schema.svg)).

**Ojo con `dim_tiempo`**: no es un calendario clásico de 365 días, es un
timestamp por evento (casi 1 fila de dimensión por cada fila de hecho,
porque el dataset es de eventos puntuales, no de ventas diarias). Por eso
**no la marques como "Tabla de fechas"** en Power BI — esa opción espera una
fecha por día sin huecos ni repetidos, y acá no aplica. Para agrupar por
mes/día/hora usá directamente las columnas `year`, `month`, `day`, `hour`,
`weekday` que ya vienen calculadas en la tabla.

## 3. Medidas DAX

Creá una tabla nueva vacía (`Modelado` → `Nueva tabla`, poné algo tipo
`_Medidas = ROW("x", 1)`) y ahí colgá estas medidas para tener todo
ordenado en una carpeta aparte del modelo:

```dax
Total Eventos = COUNTROWS(fact_envio_evento)

Tiempo Espera Promedio = AVERAGE(fact_envio_evento[Waiting_Time])

Monto Transacciones = SUM(fact_envio_evento[User_Transaction_Amount])

Utilizacion Promedio Activo = AVERAGE(fact_envio_evento[Asset_Utilization])

Inventario Promedio = AVERAGE(fact_envio_evento[Inventory_Level])

Demanda Pronosticada Total = SUM(fact_envio_evento[Demand_Forecast])

Eventos Con Demora =
CALCULATE(
    [Total Eventos],
    dim_demora[Logistics_Delay] = TRUE
)

% Eventos Con Demora =
DIVIDE([Eventos Con Demora], [Total Eventos])

Eventos Sin Demora Con Motivo Cargado =
CALCULATE(
    [Total Eventos],
    fact_envio_evento[_dq_delay_reason_mismatch] = TRUE
)

Eventos Delivered =
CALCULATE([Total Eventos], dim_estado_envio[Shipment_Status] = "Delivered")

Eventos In Transit =
CALCULATE([Total Eventos], dim_estado_envio[Shipment_Status] = "In Transit")

Eventos Delayed =
CALCULATE([Total Eventos], dim_estado_envio[Shipment_Status] = "Delayed")

Demanda Pronosticada Promedio = AVERAGE(fact_envio_evento[Demand_Forecast])
```

Notas rápidas:
- `_dq_delay_reason_mismatch` es la columna que dejó marcada silver para el
  hallazgo de calidad que ya charlamos (filas sin demora que igual traen
  motivo cargado) — la última medida sirve para mostrarlo en el dashboard
  como nota de calidad de datos, no como error a "corregir".
- Si esa columna no llegó a Power BI, es porque en la importación del
  parquet quedó oculta o filtrada; revisá que `fact_envio_evento` tenga
  todas sus columnas en el panel de campos.
- Las tres medidas `Eventos Delivered/In Transit/Delayed` filtran por los
  valores reales de `Shipment_Status` en el dataset — si en tu corrida
  aparecen otros textos, ajustá el filtro con esos valores.

## 4. Layout sugerido del dashboard

Se armó tomando como referencia un dashboard de logística clásico: 3 paneles
arriba (gauge + 2 donas) y 2 paneles abajo (KPIs con ícono + gráfico
combinado). La idea es reproducir esa misma grilla con las métricas de este
dataset.

```
┌───────────────┬───────────────────┬──────────────────────┐
│    Fleet      │  Delivery Status   │  Eventos por Tráfico  │
│   (gauge)     │     (dona)         │       (dona)          │
├───────────────┼───────────────────┼──────────────────────┤
│ tabla resumen │   tabla resumen    │    tabla resumen      │
├───────────────┴───────────────────┴──────────────────────┤
│  KPIs ícono   │   Tiempo de Espera y Demanda por Mes       │
│ (reloj/caja)  │        (barras + línea)                    │
└───────────────┴─────────────────────────────────────────┘
```

**Panel 1 — "Fleet" (arriba izquierda):**
- Visual **Medidor (Gauge)**: valor = `Utilizacion Promedio Activo`,
  mínimo 0, máximo 100, con rangos de color rojo/amarillo/verde igual que
  el ejemplo (podés poner el objetivo en 80).
- Tabla chica debajo, título "Eficiencia de Flota":
  `Total Activos` (usá `COUNTROWS(dim_activo)` como medida rápida),
  `Eventos Delivered`, `Eventos In Transit`, `Eventos Delayed`.

**Panel 2 — "Delivery Status" (arriba centro):**
- Visual **Gráfico de anillo (Donut)**: `Eventos Con Demora` vs
  `Total Eventos - Eventos Con Demora` (podés crear una medida
  `Eventos Sin Demora = [Total Eventos] - [Eventos Con Demora]`), mostrando
  `% Eventos Con Demora` como texto central.
- Tabla debajo: `Eventos Con Demora` / `Eventos Sin Demora` con sus valores.

**Panel 3 — "Eventos por Tráfico" (arriba derecha):**
- Visual **Donut**: `Total Eventos` por `dim_trafico[Traffic_Status]`
  (reemplaza el "Deliveries by Destination" del ejemplo — acá no hay
  destino/país, pero el rol visual es el mismo: distribución categórica).
- Tabla/leyenda debajo con el % de cada estado de tráfico (Power BI lo
  calcula solo si activás "Mostrar valores como % del total" en el visual).

**Panel 4 — KPIs con ícono (abajo izquierda):**
Dos tarjetas grandes con ícono, como en el ejemplo del reloj y la caja:
- 🕐 `Tiempo Espera Promedio` (formateado como minutos).
- 📦 `Inventario Promedio` (formateado como unidades) — o cambialo por
  `Demanda Pronosticada Promedio` si preferís mostrar demanda en vez de
  inventario.
  Podés usar el visual nativo **Tarjeta** y pegarle un ícono al lado con
  un elemento de forma/imagen, o instalar un custom visual tipo "KPI card
  with icon" desde AppSource si querés que quede idéntico al ejemplo.

**Panel 5 — Gráfico combinado (abajo derecha):**
- Visual **Gráfico de barras y líneas (Combo chart)**:
  eje de categorías = `dim_tiempo[month]` (o `year`+`month` si tenés varios
  años), columnas = `Tiempo Espera Promedio`, línea (eje secundario) =
  `Demanda Pronosticada Promedio`. Es el equivalente a "Loading Time &
  Weight" del ejemplo, mostrando dos métricas relacionadas en el tiempo.

**Segmentadores (slicers) sugeridos, arriba de todo o en un panel lateral:**
`dim_activo[Asset_ID]`, `dim_estado_envio[Shipment_Status]`,
`dim_tiempo[year]`/`[month]` — así el resto del dashboard se filtra en
conjunto.

**Opcional — panel geográfico:** si querés agregar una fila más abajo,
un visual de **Mapa** con `Latitude`/`Longitude` de `fact_envio_evento`,
coloreado por `dim_estado_envio[Shipment_Status]`, complementa bien este
layout aunque no esté en la referencia.

### Paleta de colores

El ejemplo usa turquesa/verde azulado como color principal sobre fondo
gris claro en los paneles y blanco en el resto. Para replicarlo rápido:
`Ver` → `Temas` → `Personalizar el tema actual` → color principal
`#00B3A6` (turquesa), fondo de página `#FFFFFF`, y ponele `#F2F2F2` de
fondo a los rectángulos/paneles que agrupan cada sección (`Insertar` →
`Forma` → rectángulo redondeado, detrás de los visuales, sin borde).

## 5. Guardado

Guardá como `.pbix` dentro de una carpeta `powerbi/` en este mismo proyecto
(creala si no existe) para que quede versionado junto con el resto del
pipeline. Los `.pbix` son binarios, así que no aportan mucho a un diff de
git, pero al menos queda todo en el mismo repo.
