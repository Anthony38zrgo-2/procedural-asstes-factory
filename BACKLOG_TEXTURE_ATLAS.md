# Backlog — Curación de texturas y generación determinista de atlas

## Objetivo

Construir un pipeline reproducible que convierta las texturas recuperadas de
`assets-texturas` en una biblioteca curada y trazable, y que genere atlas nuevos
combinando cortezas, hojas y ramillas existentes sin perder la estética gráfica
de un juego de 2004–2006.

El mismo conjunto de fuentes, receta, semilla y versión del generador debe
producir exactamente el mismo resultado.

## Alcance inicial

- Ingerir y analizar las texturas recuperadas de vegetación.
- Verificar la asociación entre índice recuperado y nombre candidato.
- Detectar imágenes corruptas, incompletas, duplicadas o inadecuadas.
- Limpiar alpha, halos y bordes de sprites.
- Separar ramillas o grupos de hojas reutilizables.
- Clasificar cortezas y follaje mediante metadatos explícitos.
- Generar atlas de 256×256 y 512×512 mediante recetas deterministas.
- Crear variantes cromáticas y estacionales derivadas de fuentes existentes.
- Producir manifiestos de procedencia, hashes y reportes visuales.
- Validar los atlas en planos de follaje renderizados por Blender.

## Fuera del alcance de esta fase

- Generación de imágenes completamente nuevas mediante modelos generativos.
- Sustitución de las fuentes recuperadas por fotografías modernas.
- Materiales PBR complejos de alta resolución.
- Implementación completa del nuevo generador de mallas de vegetación.
- Publicación automática de todos los atlas sin revisión visual humana.

## Principios del pipeline

1. Las fuentes originales nunca se modifican.
2. Todo archivo derivado debe registrar sus fuentes y operaciones.
3. La semilla de composición no debe alterar las fuentes seleccionadas fuera de
   los rangos permitidos por la receta.
4. El color no debe cambiar la geometría ni la distribución UV del asset.
5. Los atlas deben favorecer alpha test y mipmaps, no transparencia mezclada.
6. Los cambios de tono deben conservar luminancia, variación local y detalle.
7. Una textura con nombre incierto no se publica sin un nivel de confianza y
   evidencia registrados.

## Definición de terminado global

Una historia se considera terminada cuando:

- Tiene pruebas automatizadas proporcionales al riesgo.
- Sus salidas incluyen SHA-256 de fuentes, receta y archivos generados.
- No modifica archivos dentro de `assets-texturas/textures/*/{dds,png}`.
- Puede ejecutarse desde una ruta limpia siguiendo instrucciones documentadas.
- Dos ejecuciones consecutivas producen el mismo manifiesto y los mismos bytes.
- Los errores identifican la textura y la operación que falló.
- Los reportes visuales permiten revisar el resultado sin abrir cada imagen.

## Prioridades

- **P0:** necesario para el primer atlas utilizable.
- **P1:** necesario para una biblioteca de producción.
- **P2:** expansión o mejora posterior.

Las estimaciones usan S, M y L como tamaño relativo, no como duración.

---

## Épica TX-0 — Fundaciones y contrato determinista

### TX-001 — Normalizar la estructura de directorios

- **Prioridad:** P0
- **Tamaño:** S
- **Dependencias:** ninguna
- **Trabajo:** definir ubicaciones para fuentes, catálogo, recetas, staging,
  outputs publicados, reportes y caché descartable. Corregir las referencias
  heredadas a `game/resources/environment` para que funcionen desde la raíz
  actual del repositorio.
- **Criterios de aceptación:** ninguna salida generada se mezcla con las fuentes;
  todas las rutas de manifiesto son relativas a la raíz; el pipeline funciona
  aunque la raíz del repositorio cambie.

### TX-002 — Declarar entorno y dependencias

- **Prioridad:** P0
- **Tamaño:** S
- **Dependencias:** TX-001
- **Trabajo:** añadir configuración de Python, versiones compatibles y comandos
  documentados. Registrar también la versión de Blender utilizada en trabajos
  que dependan de Blender.
- **Criterios de aceptación:** existe un único procedimiento reproducible de
  instalación; una comprobación previa informa dependencias ausentes o versiones
  incompatibles.

### TX-003 — Definir el esquema de procedencia

- **Prioridad:** P0
- **Tamaño:** M
- **Dependencias:** TX-001
- **Trabajo:** definir JSON Schema para fuentes y derivados con identificador,
  ruta, hash, dimensiones, espacio de color, canal alpha, nombre candidato,
  confianza, etiquetas, operaciones, semilla y versión del generador.
- **Criterios de aceptación:** el esquema rechaza fuentes sin hash y derivados
  sin procedencia; todas las rutas son canónicas; las listas se serializan con
  orden estable.

### TX-004 — Implementar namespaces de semillas

- **Prioridad:** P0
- **Tamaño:** S
- **Dependencias:** TX-003
- **Trabajo:** separar semillas para selección, transformación cromática,
  empaquetado y variantes estacionales.
- **Criterios de aceptación:** cambiar la semilla cromática no cambia la selección
  ni el layout; cambiar la semilla de layout no cambia los píxeles de cada sprite.

### TX-005 — Añadir verificación de reproducibilidad

- **Prioridad:** P0
- **Tamaño:** M
- **Dependencias:** TX-002, TX-003, TX-004
- **Trabajo:** ejecutar cada receta dos veces en staging independiente y comparar
  manifiestos, hashes y bytes.
- **Criterios de aceptación:** el comando falla ante cualquier diferencia y
  muestra el primer archivo u operación divergente.

---

## Épica TX-1 — Inventario y curación del banco recuperado

### TX-010 — Ingerir los manifiestos recuperados

- **Prioridad:** P0
- **Tamaño:** M
- **Dependencias:** TX-003
- **Trabajo:** unificar los CSV y metadatos de `objects_core`, preservando índice,
  nombre candidato, dimensiones, formato, modo y offset recuperado.
- **Criterios de aceptación:** las 140 imágenes PNG y sus DDS correspondientes
  aparecen en el catálogo; faltantes y colisiones de índice son errores.

### TX-011 — Calcular métricas técnicas por textura

- **Prioridad:** P0
- **Tamaño:** M
- **Dependencias:** TX-010
- **Trabajo:** medir cobertura alpha, bounding box visible, histograma, rango de
  luminancia, píxeles transparentes con RGB contaminado, entropía, bordes,
  posible tileabilidad y relación de aspecto.
- **Criterios de aceptación:** todas las entradas tienen métricas deterministas;
  imágenes opacas, vacías o casi transparentes quedan señaladas.

### TX-012 — Detectar duplicados y variantes casi idénticas

- **Prioridad:** P1
- **Tamaño:** M
- **Dependencias:** TX-011
- **Trabajo:** combinar hash exacto y hash perceptual para encontrar copias,
  recolores y versiones con alpha diferente.
- **Criterios de aceptación:** el reporte distingue duplicado exacto de similitud;
  no elimina archivos automáticamente.

### TX-013 — Generar hojas de contacto de curación

- **Prioridad:** P0
- **Tamaño:** S
- **Dependencias:** TX-011
- **Trabajo:** producir hojas de contacto con índice, nombre candidato, tamaño,
  cobertura alpha, confianza y alertas técnicas.
- **Criterios de aceptación:** se generan vistas sobre fondo negro, blanco y
  checkerboard; cada celda puede relacionarse inequívocamente con el catálogo.

### TX-014 — Crear clasificación semántica revisable

- **Prioridad:** P0
- **Tamaño:** M
- **Dependencias:** TX-013
- **Trabajo:** etiquetar `bark`, `foliage_cluster`, `single_leaf`, `branchlet`,
  `conifer`, `broadleaf`, `bush`, `season`, `snow`, `shadow`, `corrupt` y
  `unknown`. Registrar confianza `verified`, `probable` o `unverified`.
- **Criterios de aceptación:** ninguna fuente `unknown`, `corrupt` o
  `unverified` entra en la allowlist de producción.

### TX-015 — Verificar nombres mediante metadatos y modelos recuperados

- **Prioridad:** P0
- **Tamaño:** L
- **Dependencias:** TX-010, TX-014
- **Trabajo:** contrastar orden recuperado, referencias XML, UVs de los modelos
  vegetales y contenido visual para confirmar nombres como `leaves_acer_*`,
  `leaves_germany_*`, `leaves_safari` y `trunk_*`.
- **Criterios de aceptación:** cada asociación verificada incluye evidencia; las
  asociaciones ambiguas conservan el índice como identidad primaria.

### TX-016 — Publicar la allowlist inicial

- **Prioridad:** P0
- **Tamaño:** S
- **Dependencias:** TX-014, TX-015
- **Trabajo:** seleccionar las fuentes aptas para el piloto: al menos dos
  cortezas, tres familias broadleaf, una de arbusto y una de conífera.
- **Criterios de aceptación:** la selección excluye corrupción visible, alpha
  inútil y procedencia ambigua; cada exclusión importante registra una razón.

---

## Épica TX-2 — Normalización y extracción de sprites

### TX-020 — Normalizar espacio de color y alpha

- **Prioridad:** P0
- **Tamaño:** M
- **Dependencias:** TX-016
- **Trabajo:** convertir fuentes aprobadas a RGBA sRGB con reglas explícitas,
  preservando una copia bit a bit de la entrada y evitando premultiplicación
  accidental.
- **Criterios de aceptación:** una prueba con bordes semitransparentes conserva
  color y cobertura; el manifiesto registra la conversión.

### TX-021 — Limpiar halos y extender color bajo alpha

- **Prioridad:** P0
- **Tamaño:** M
- **Dependencias:** TX-020
- **Trabajo:** rellenar RGB en píxeles transparentes desde el borde visible y
  aplicar dilation configurable sin expandir la máscara publicada.
- **Criterios de aceptación:** no aparecen bordes blancos u oscuros en fondos de
  contraste ni al reducir la textura; la operación es idempotente.

### TX-022 — Extraer componentes de follaje

- **Prioridad:** P0
- **Tamaño:** L
- **Dependencias:** TX-020
- **Trabajo:** detectar componentes conectados o regiones de atlas que representen
  ramillas y grupos de hojas. Permitir correcciones manuales declarativas en JSON,
  sin editar píxeles a mano.
- **Criterios de aceptación:** cada sprite tiene rectángulo fuente, máscara,
  padding, punto de anclaje y orientación principal; componentes diminutos se
  filtran mediante umbral registrado.

### TX-023 — Definir anclas y orientación de ramillas

- **Prioridad:** P0
- **Tamaño:** M
- **Dependencias:** TX-022
- **Trabajo:** registrar base de la ramilla, punta, eje de crecimiento, escala
  relativa y si admite espejo o rotación.
- **Criterios de aceptación:** el visualizador muestra ancla y eje; ningún sprite
  direccional se rota o refleja fuera de lo permitido.

### TX-024 — Preparar cortezas tileables

- **Prioridad:** P1
- **Tamaño:** M
- **Dependencias:** TX-020
- **Trabajo:** crear recortes verticales, corregir costuras cuando sea necesario y
  registrar escala física aproximada. No suavizar el detalle característico.
- **Criterios de aceptación:** la prueba de repetición 3×3 no muestra una costura
  dominante; la fuente y el recorte quedan registrados.

### TX-025 — Generar previews individuales normalizados

- **Prioridad:** P0
- **Tamaño:** S
- **Dependencias:** TX-021, TX-022, TX-023
- **Trabajo:** mostrar cada sprite sobre checkerboard y aplicado a un plano con
  alpha test.
- **Criterios de aceptación:** los previews incluyen nombre estable, dimensiones,
  ancla y fuente.

---

## Épica TX-3 — Recetas y composición de atlas

### TX-030 — Definir el esquema de receta de atlas

- **Prioridad:** P0
- **Tamaño:** M
- **Dependencias:** TX-003, TX-023
- **Trabajo:** especificar tamaño, padding, familia, filtros de selección, pesos,
  cantidad de sprites, escalas, transformaciones permitidas, semilla y reglas de
  color.
- **Criterios de aceptación:** el esquema rechaza fuentes no aprobadas,
  transformaciones incompatibles y padding insuficiente.

### TX-031 — Implementar empaquetador determinista

- **Prioridad:** P0
- **Tamaño:** L
- **Dependencias:** TX-030
- **Trabajo:** empaquetar sprites mediante orden canónico y desempate estable.
  Generar textura, mapa de regiones UV y manifiesto.
- **Criterios de aceptación:** no hay solapamientos; todas las regiones respetan
  padding; mismos inputs generan exactamente el mismo layout.

### TX-032 — Implementar composición cromática contenida

- **Prioridad:** P0
- **Tamaño:** M
- **Dependencias:** TX-030
- **Trabajo:** permitir variación por sprite de luminancia, saturación y matiz
  dentro de rangos estrechos, preservando detalle y alpha.
- **Criterios de aceptación:** el alpha no cambia; las métricas de contraste local
  permanecen dentro de tolerancia; no se producen colores neón ni uniformes.

### TX-033 — Generar variantes estacionales

- **Prioridad:** P1
- **Tamaño:** M
- **Dependencias:** TX-032
- **Trabajo:** crear verde, seco, amarillo, cobre y rojo mediante curvas y máscaras
  reproducibles. Mezclar hojas en distintas fases dentro del mismo atlas.
- **Criterios de aceptación:** todas las estaciones comparten layout UV; el cambio
  de estación solo afecta píxeles y metadatos de apariencia.

### TX-034 — Generar atlas de follaje de 256 y 512 px

- **Prioridad:** P0
- **Tamaño:** M
- **Dependencias:** TX-031, TX-032
- **Trabajo:** publicar resoluciones objetivo desde una composición canónica,
  usando reducción con alpha correcto.
- **Criterios de aceptación:** las regiones conservan cobertura y separación en
  ambas resoluciones; cada salida tiene hash y mapa UV propio.

### TX-035 — Generar atlas mixtos de ramillas

- **Prioridad:** P1
- **Tamaño:** L
- **Dependencias:** TX-031, TX-034
- **Trabajo:** componer ramillas nuevas a partir de varios componentes compatibles,
  manteniendo una dirección de crecimiento legible y evitando colisiones visuales.
- **Criterios de aceptación:** cada ramilla compuesta enumera todos sus componentes;
  la base queda despejada para conectarla a geometría; un revisor puede desactivar
  composiciones concretas mediante receta.

### TX-036 — Crear recetas piloto

- **Prioridad:** P0
- **Tamaño:** S
- **Dependencias:** TX-034
- **Trabajo:** crear tres recetas: broadleaf verde, arbusto seco/verde y conífera.
- **Criterios de aceptación:** cada receta contiene al menos cuatro regiones útiles,
  utiliza solo la allowlist y pasa reproducibilidad.

---

## Épica TX-4 — Mipmaps, formatos y material de prueba

### TX-040 — Generar mipmaps preservando alpha coverage

- **Prioridad:** P0
- **Tamaño:** L
- **Dependencias:** TX-034
- **Trabajo:** construir la cadena de mipmaps ajustando el umbral o la cobertura
  para reducir el parpadeo y evitar que las hojas desaparezcan a distancia.
- **Criterios de aceptación:** la cobertura visible se mantiene dentro de una
  tolerancia definida en todos los niveles; no hay bleeding entre regiones.

### TX-041 — Definir perfiles de exportación

- **Prioridad:** P1
- **Tamaño:** M
- **Dependencias:** TX-040
- **Trabajo:** publicar PNG canónico y, cuando el consumidor lo requiera, DDS u
  otro formato comprimido. Mantener el PNG como fuente derivada verificable.
- **Criterios de aceptación:** cada formato registra herramienta y parámetros;
  las diferencias visuales están dentro de tolerancia.

### TX-042 — Crear material GLB de referencia

- **Prioridad:** P0
- **Tamaño:** M
- **Dependencias:** TX-034
- **Trabajo:** crear material double-sided con `alphaMode=MASK`, cutoff configurable,
  textura sRGB y vertex color opcional para AO.
- **Criterios de aceptación:** Blender y el visor glTF muestran transparencia
  correcta; el material no usa alpha blend; no hay halos perceptibles.

### TX-043 — Crear geometría de prueba neutral

- **Prioridad:** P0
- **Tamaño:** S
- **Dependencias:** TX-042
- **Trabajo:** generar un conjunto fijo de planos cruzados, inclinados y vistos a
  contraluz para evaluar cada atlas de forma comparable.
- **Criterios de aceptación:** todos los atlas se prueban con idéntica geometría,
  cámara e iluminación.

---

## Épica TX-5 — QA visual y publicación

### TX-050 — Renderizar matriz de validación en Blender

- **Prioridad:** P0
- **Tamaño:** M
- **Dependencias:** TX-043
- **Trabajo:** renderizar fondos negro, blanco y checkerboard; luz frontal,
  lateral y contraluz; vistas cercana, media y distante.
- **Criterios de aceptación:** cada atlas produce una hoja de revisión estable con
  receta, hash y versión de Blender.

### TX-051 — Detectar bleeding, halos y pérdida de cobertura

- **Prioridad:** P0
- **Tamaño:** M
- **Dependencias:** TX-040, TX-050
- **Trabajo:** añadir comparaciones automáticas por fondo y mip para encontrar
  contaminación de color, bordes y desaparición prematura.
- **Criterios de aceptación:** los umbrales están documentados; los fallos señalan
  región y nivel de mip afectados.

### TX-052 — Crear revisión lado a lado con fuentes

- **Prioridad:** P0
- **Tamaño:** S
- **Dependencias:** TX-050
- **Trabajo:** generar una hoja con fuente recuperada, sprites extraídos, atlas
  compuesto y render sobre planos.
- **Criterios de aceptación:** la procedencia visual puede verificarse sin consultar
  archivos adicionales.

### TX-053 — Publicar catálogo versionado

- **Prioridad:** P0
- **Tamaño:** M
- **Dependencias:** TX-005, TX-051, TX-052
- **Trabajo:** publicar únicamente outputs aprobados con manifiesto, recetas,
  mapas UV, texturas y reportes.
- **Criterios de aceptación:** publicación atómica desde staging; un fallo no deja
  un catálogo parcial; todos los hashes se verifican después de publicar.

### TX-054 — Añadir auditoría de regresión

- **Prioridad:** P1
- **Tamaño:** M
- **Dependencias:** TX-053
- **Trabajo:** comparar nueva versión contra la publicada y clasificar cambios de
  píxel, layout, fuentes o metadatos.
- **Criterios de aceptación:** ningún cambio visual silencioso puede publicarse;
  los cambios intencionales requieren actualización explícita de snapshot.

---

## Épica TX-6 — Integración piloto con vegetación procedural

### TX-060 — Integrar atlas broadleaf en un árbol piloto

- **Prioridad:** P0
- **Tamaño:** L
- **Dependencias:** TX-042, TX-053
- **Trabajo:** sustituir hojas hexagonales por planos de ramillas texturizadas en
  un único árbol, conservando su receta estructural.
- **Criterios de aceptación:** el GLB contiene UVs y textura; mantiene el presupuesto
  objetivo; no hay planos flotantes; supera al asset actual en revisión lado a lado.

### TX-061 — Integrar atlas de arbusto en un piloto

- **Prioridad:** P0
- **Tamaño:** M
- **Dependencias:** TX-060
- **Trabajo:** validar densidad, cruces de planos y lectura a ras del suelo.
- **Criterios de aceptación:** la base no forma un bloque opaco; se distinguen
  huecos, tallos y profundidad desde al menos tres vistas.

### TX-062 — Integrar atlas de conífera en un piloto

- **Prioridad:** P1
- **Tamaño:** L
- **Dependencias:** TX-060
- **Trabajo:** validar ramillas direccionales y distribución por pisos sin reutilizar
  las reglas de broadleaf.
- **Criterios de aceptación:** la silueta es cónica e irregular; las ramillas siguen
  ramas de soporte; no se percibe como planos horizontales apilados.

### TX-063 — Comparar contra modelos recuperados

- **Prioridad:** P1
- **Tamaño:** M
- **Dependencias:** TX-060, TX-061, TX-062
- **Trabajo:** comparar presupuesto, cobertura de silueta, densidad y respuesta a
  distancia con los modelos vegetales recuperados.
- **Criterios de aceptación:** el reporte distingue objetivos alcanzados y brechas;
  no exige copiar exactamente la topología original.

### TX-064 — Aprobar expansión a la biblioteca completa

- **Prioridad:** P0
- **Tamaño:** S
- **Dependencias:** TX-060, TX-061, TX-063
- **Trabajo:** revisión de los pilotos y decisión de ajustar o extender el sistema
  a las doce familias actuales.
- **Criterios de aceptación:** existe una decisión registrada con atlas aprobados,
  presupuestos, cutoff alpha y reglas morfológicas que pueden escalarse.

---

## Orden de ejecución recomendado

### Hito A — Banco confiable

TX-001 → TX-002 → TX-003 → TX-010 → TX-011 → TX-013 → TX-014 → TX-015 → TX-016

**Resultado:** catálogo de fuentes verificadas y allowlist inicial.

### Hito B — Sprites limpios

TX-004 → TX-020 → TX-021 → TX-022 → TX-023 → TX-025

**Resultado:** ramillas y grupos de hojas normalizados, con anclas y procedencia.

### Hito C — Primer atlas determinista

TX-030 → TX-031 → TX-032 → TX-034 → TX-036 → TX-005

**Resultado:** tres atlas piloto repetibles byte a byte.

### Hito D — Validación visual

TX-040 → TX-042 → TX-043 → TX-050 → TX-051 → TX-052 → TX-053

**Resultado:** atlas publicados con material y QA de alpha/mipmaps.

### Hito E — Prueba en vegetación

TX-060 → TX-061 → TX-063 → TX-064

**Resultado:** un árbol y un arbusto piloto que permiten decidir la expansión.

## Primer incremento recomendado

El primer incremento debe terminar en TX-016. No conviene comenzar a componer
atlas antes de confirmar cuáles imágenes son realmente cortezas, hojas o ramillas
y cuáles asociaciones de nombres son confiables. El segundo incremento debe
producir un único atlas broadleaf verde de 512×512, antes de crear variantes
estacionales o múltiples familias.
