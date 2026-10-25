# XQC — estado vigente

Actualización documental: **24 de octubre de 2026**. Este documento sintetiza la
baseline observada y las decisiones del usuario; no es una nueva certificación QC.

## 1. Identificación del proyecto

**XQC** es el repositorio; **Audio Delivery QC Inspector** es su producto principal.
Aplicación Python local, CLI y GUI PySide6, para inspección técnica de entregas de
cine y televisión sin modificar las fuentes. Véase [README](README.md).

## 2. Commit y versión de referencia

- M5 **aceptado por el usuario**: `d339b70026a1941ee732a5eb7962581aab0ad6c7`.
- Baseline verificada en Git e identificada por el tag anotado `m5-accepted`,
  creado y publicado en `origin` el 18 de octubre de 2026.
- Versión declarada: `1.0.0` en [pyproject.toml](pyproject.toml) y
  [audio_qc](src/audio_qc/__init__.py); informes nuevos JSON schema **5** en la rama M6; baseline M5 schema **4**.
- Congelar M5 antes de M6 es una decisión del usuario. El tag identifica la baseline
  aceptada; los commits documentales posteriores no cambian esa referencia.

## 3. Arquitectura general

| Área | Implementación observada |
| --- | --- |
| Entrada y configuración | `cli.py`, `gui_window.py`, `spec_editor.py`, `config.py`; GUI delega en CLI con snapshot de configuración |
| Medición | `scanner.measure_file`, `measurement.py`, `samples.py`, `loudness.py`, `metadata.py`, `bwf.py`; FFmpeg/ffprobe y procesamiento por bloques |
| Evidencia y agrupación | `defects.py`, `consolidation.py`, `issues.py`, `programme.py`, `snippets.py` |
| Política QC | `rules.measurement_requirements`, `rules.assess_file`; evaluación separada de los hechos medidos |
| Presentación | `reports/`, `timecode.py`; JSON/HTML/CSV, navegación TC y provenance |

Código en [src/audio_qc](src/audio_qc), pruebas en [tests](tests), utilidades en
[scripts](scripts), presets en [config](config). La inspección estática no sustituye
la ejecución de estas rutas.

## 4. Funcionalidades implementadas

Observadas en código y documentación de la baseline:

- Descubrimiento recursivo; metadatos técnicos/BWF, análisis de muestras, hashes
  opcionales y medición EBU R128 por archivo físico.
- Presets y especificación CUSTOM validada; separación medición/política M3,
  configuración e interfaz M4 y contrato de fiabilidad del hotfix.
- Candidatos de clicks/ticks y dropouts, consolidación intra/cross-channel M3.1,
  muestras exactas, límites de memoria/candidatos y snippets de evidencia.
- TC de reporting configurable, incluidos formatos fraccionales y 29.97 DF;
  fuentes AUTO, FILE_RELATIVE y MANUAL. Detección independiente del frame rate.
- M5: grupos multiple-mono opcionales mediante manifest YAML o convención de
  sufijos exactos, con validación posterior; stereo L/R y 5.1 L/R/C/LFE/Ls/Rs.
  Cada miembro debe ser mono PCM, de igual sample rate y longitud exacta.
- Alineación conservadora M5: BWF exige TimeReference idénticos; `common_file_start`
  es una afirmación explícita. `auto` admite ausencia de BWF en todos los miembros
  con aviso, pero rechaza mezcla de referencias presentes/ausentes. No infiere
  offsets ni rollover. Véanse [reglas vigentes](docs/PROGRAMME_GROUPS.md).
- Issues de grupo con provenance por fuente, mayor severidad ya evaluada, enlaces
  de evidencia mono y recuentos separados de archivos/grupos. Resumen HTML por
  categoría con detalles desplegables; no se sintetiza un master interleaved.

## 5. Funcionalidades verificadas

**Histórico, no repetido en esta tarea:** el
[seguimiento M5 del 17/10](docs/M5_REAL_WORLD_FOLLOWUP.md) registra pruebas de
agrupación, severidad, parser, configuración GUI y regresión del hotfix. El caso
real de seis BWF mono verificó posiciones, medidas preservadas e integridad de
SHA-256/tamaño/mtime. La última corrección de severidad se comprobó reutilizando
los hechos medidos para reconstruir grupos/reportes, no mediante un segundo decode.

La publicación anterior registró CI satisfactoria para Python 3.11, Python 3.14 y
auditoría de dependencias en el [run 38981882091](https://github.com/GuerraMagica/Sound_QC/actions/runs/38981882091)
del commit aceptado. **No consultado de nuevo en esta tarea**; no se afirma estado
remoto actual. GUI offscreen no equivale a validación manual en Pro Tools/Resolve.

**Actual (M6):** implementación en `codex/m6-programme-measurement`, con
commit y push de esta rama autorizados por el usuario. Diseño y plan aprobados. Mediciones
virtuales stereo/5.1, scope de política, schema 5 y cancelación GUI/CLI implementados;
[registro M6](docs/M6_VALIDATION.md) distingue pruebas ejecutadas y aceptación
pendiente. CI remota, Linux y validación profesional no revalidados.

## 6. Limitaciones conocidas

- La baseline M5 no mide niveles combinados. M6 los mide solo en grupos elegibles;
  un grupo M5 VALID puede ser inelegible para M6 por timing insuficiente.
  `VALID` continúa expresando validez estructural, no cumplimiento. En M6, mono
  es diagnóstico y los targets se evalúan sobre el programa. Aceptación profesional
  y Linux pendientes; no confundir implementación local con release aceptada.
- Los caps pueden dejar cobertura `INCOMPLETE`. El caso real retuvo 1.957 issues de
  archivo y 1.000 de grupo (995 clicks/ticks y 5 dropouts); no son un total global
  de defectos únicos ni una inspección completa. No ocultar avisos de truncamiento.
- El origen interno de los NaN M/S de FFmpeg 9.0.2 sigue sin resolver. Las métricas
  afectadas quedan null/ERROR; Integrated válido se conserva independientemente.
- Detectores heurísticos requieren escucha humana. TC compartido o snippets
  solapados no prueban que dos eventos sean el mismo defecto. El benchmark pequeño
  no establece una tasa profesional de falsos positivos.
- True Peak se reporta con resolución de 0,1 dB; metadata iXML/ADM y otros formatos
  BWF no se interpretan íntegramente. Para detalle véase README.
- No se demostró una desincronización histórica de True Peak en GUI: la captura
  pudo reflejar una edición posterior. Los tests históricos verificaron −1 dBTP
  activo y el snapshot; queda pendiente la nueva prueba del operador.
- No se completó inspección visual automatizada del HTML local por restricción
  del navegador. Parte de la evidencia real está excluida de Git, por privacidad,
  y no estará disponible en cualquier clon.

## 7. Estado de las pruebas

Resultado **histórico** del seguimiento M5: **137 focalizadas y 627 completas**,
cero fallos y cero omitidas; Python 3.14.8, macOS 26.5.2 ARM64, FFmpeg 9.0.2.
El hotfix documenta aceptación operativa A–F. Estos resultados M5 son históricos;
las comprobaciones nuevas se registran separadamente en M6_VALIDATION.

Para futuras tareas con ejecución autorizada, desde `audio-delivery-qc/`:

```sh
source .venv/bin/activate
python -m pytest -q
python scripts/verify_hotfix_release.py --output /tmp/audio-qc-acceptance-NEW
```

Comandos tomados del README; usar salida nueva. Los comandos focalizados están en
[seguimiento M5](docs/M5_REAL_WORLD_FOLLOWUP.md); la validación de grupos en
[Programme Groups](docs/PROGRAMME_GROUPS.md). La
[CI](../.github/workflows/tests.yml) configura Linux/Qt offscreen y auditoría de
dependencias. Su definición no demuestra por sí sola una ejecución satisfactoria.

## 8. Decisiones técnicas vigentes

- Congelar funcionalidad M5 durante M6; solo corregir regresiones demostradas y
  autorizadas. No avanzar milestones implícitamente.
- Medición/evidencia, política y presentación permanecen separadas. No inventar
  severidades al medir; conservar la mayor clasificación existente al agrupar.
- `sample_index` relativo al archivo es autoritativo. Para BWF:
  `absolute_sample = TimeReference + sample_index`. OriginationTime y TC visible
  no son sustitutos de ese cálculo entero.
- Agrupar por tipo/canal e inicio de cluster dentro de la ventana fija del primer
  inicio (1 ms por defecto), sin chaining cross-channel ni criterio de overlap solo.
- Preservar fuentes, orden de canales, precisión, provenance y límites de memoria.
  La migración a schema 5 fue aprobada con el diseño M6; conservar columnas CSV
  y provenance. Los reportes históricos schema 4 permanecen intactos.
- Separar SUCCESS/UNAVAILABLE/ERROR, ejecución y cumplimiento acústico. El marcador
  `QC_COMPLETE.json` confirma entrega del reporte, no un PASS del audio.

## 9. Trabajo pendiente

| Milestone / decisión | Estado y autorización |
| --- | --- |
| M5 y seguimiento de fiabilidad | Implementado y aceptado por el usuario; validaciones históricas arriba |
| Documentación V1.0 | Implementada en AGENTS, PROJECT_STATE y enlace README; sin cambios funcionales |
| Tag de baseline M5 | `m5-accepted`: anotado, creado y publicado sobre el commit aceptado |
| M6: medición multicanal virtual | Implementación local autorizada y en validación; aceptación/release pendientes; ver registro M6 |
| M7: clicks/ticks | Posterior a M6; mejorar precisión/reducir falsos positivos sin perder defectos reales; no implementado ni autorizado |
| M8: UX/reportes/manual | Posterior a M7; simplificación para facility, no implementado ni autorizado |

M6 prevé medir LUFS/LRA/dBTP de WAV mono sincronizados sin generar masters
interleaved completos, contrastando con un interleaved de referencia dentro de
tolerancias verificadas. Su aceptación futura requiere pruebas automatizadas,
regresión, integridad, validación profesional y aprobación expresa del usuario.
La especificación aportada dio lugar al [diseño M6 aprobado](docs/M6_DESIGN.md)
y al [plan aprobado](docs/superpowers/plans/2026-10-19-m6-programme-measurement.md).

## 10. Próximo objetivo aprobado

**Cambiar la sensibilidad predeterminada de clicks a `low`, validar y publicar**,
autorizado por el usuario el 20/10. Prioridad: lectura/integridad y posibles
dropouts; este ajuste no modifica esos análisis ni implementa el detector M7.
Los YAML con sensibilidad explícita conservan su valor. No autoriza merge a main,
tags ni publicación de material de producción. El límite compartido de candidatos
y los avisos de cobertura incompleta siguen vigentes.

Validación de este ajuste el 20/10: 85 pruebas focalizadas y 690 completas
aprobadas (sin fallos ni omisiones; macOS, Python 3.14.8). Comparación de los ocho
fixtures sintéticos existentes: ambos niveles detectan los cinco casos positivos
y no señalan los tres controles; los eventos de dropout son idénticos. Esto no
mide falsas alarmas sobre Foley real ni descarta pérdida de clicks más débiles.

## 11. Referencias documentales

- [Instrucciones del repositorio](../AGENTS.md) y [uso/instalación](README.md).
- [Programme Groups](docs/PROGRAMME_GROUPS.md): contrato vigente de M5.
- [Seguimiento real M5](docs/M5_REAL_WORLD_FOLLOWUP.md): correcciones y evidencia histórica.
- [M5_VALIDATION](M5_VALIDATION.md): registro anterior a la publicación inicial;
  su baseline `65a5537…` no sustituye al commit aceptado actual.
- [M3](M3_VALIDATION.md), [M3.1](M31_VALIDATION.md),
  [auditoría M3.1](M31_AUDIT.md), [M4](M4_VALIDATION.md),
  [timecode](TIMECODE_VALIDATION.md) y [hotfix](HOTFIX_IMPLEMENTATION.md): históricos.

Lectura de aparentes contradicciones: «Separate mono files never group» en README
describe M3.1 dentro de una fuente; M5 añade agrupación entre fuentes validadas.
«No M5/M6 work is included» pertenece al registro del hotfix, no al estado global.
Las cifras y limitaciones antiguas se conservan como historia; este documento
identifica su alcance sin reescribirlas ni presentar pruebas históricas como actuales.

## Experimento de confirmación de clicks (20/10/2026)

Autorizada una herramienta independiente y plantilla de anotación; el material real
se etiquetará después. Compara baseline `2e74a097455dbb30cd2f2df312e078aeae35a426`
(low) con contexto temporal y predicción lineal, sin integrar cambios en producción.
Véase [alcance, uso y criterios](docs/CLICK_EXPERIMENT.md). No supone aceptación de
un detector M7 ni modifica dropouts, política QC o capacidades de M6. La eficacia
sobre Print Masters reales queda pendiente de validación con reserva independiente.

Ampliación experimental aprobada el 22/10 y ejecutada el 23/10/2026: comparación
opcional con Essentia ClickDetector independiente y etiquetas de rechazo profesional.
Véase [protocolo v2 y validación](docs/CLICK_EXPERIMENT.md#comparación-independiente-con-essentia--protocolo-v2).
Conserva el experimento v1 y la aplicación de producción. No supone aceptación M7,
certificación Netflix ni eficacia real demostrada; instalación aislada y corpus real
pendiente. La implementación no autorizaba publicación; el usuario autorizó
posteriormente commit y push de esta ampliación en la rama actual el 23/10/2026.
Esa publicación no supone integración en main ni aceptación funcional M7.

## Respaldo de bit depth y requisito no verificable (24/10/2026)

Corrección autorizada tras auditoría local: FFprobe sigue siendo la fuente inicial;
la cabecera PCM WAV/RF64/BW64 valida o completa el dato, distinguiendo bits válidos
de almacenamiento en WAVE_FORMAT_EXTENSIBLE. Datos contradictorios o cabeceras
ambiguas dejan el valor desconocido. Un `bit_depth.required` desconocido produce
`INCOMPLETE` y salida CLI 2; un valor conocido distinto sigue siendo `FAIL`.
Sin requisito obligatorio se conserva la política de profundidad preferida.
Se añaden hechos `bwf.wave_format` y `metadata.bit_depth_provenance` al schema 5.
No se infiere resolución efectiva del contenido ni se modifican las fuentes.

Validación local ejecutada: macOS 26.5.2 ARM64, Python 3.14.8, FFmpeg 9.0.2.
140 pruebas focalizadas aprobadas; suite completa **767 aprobadas, 0 fallidas,
8 omitidas** (runtime Essentia opcional, sin `XQC_ESSENTIA_PYTHON`). Se verificaron
CLI/JSON/HTML/códigos de salida e integridad SHA-256/tamaño/mtime con WAV sintéticos.
Los seis escenarios golden M3 conservan sus valores anteriores; se validan aparte
los campos aditivos, sin regenerar el golden. La primera regresión detectó seis
fallos por esas claves nuevas antes de adaptar la comparación de estructura.

Comandos desde `audio-delivery-qc/`:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_bit_depth_resolution.py tests/test_metadata.py tests/test_policy.py tests/test_policy_baseline.py tests/test_policy_separation.py tests/test_hotfix_acceptance.py tests/test_custom_reports.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

No se ejecutó CI remota ni validación con material real. No se instalaron
dependencias ni se hizo commit/push; esta corrección no acepta M6/M7 ni resuelve
los otros hallazgos de recuperación/cobertura de la auditoría. El mapa Graphify
preexistente corresponde al commit anterior y debe contrastarse con estos cambios.

## Recuperación de mediciones ante interrupciones (24/10/2026)

Corrección autorizada de los dos huecos de recuperación detectados en la auditoría:

- Un fallo anterior a la construcción del informe conserva los archivos y programas
  ya medidos en `QC_RECOVERY.json`, sin repetir agrupación, evaluación ni formato.
  Las mediciones de programa se guardan antes de evaluar su cumplimiento QC.
- Cancelar durante SHA-256 conserva también los resultados acústicos del archivo
  en curso. El hash queda null con diagnóstico `hash_cancelled`; la evaluación
  sigue en la política y se mantiene la comprobación de cambios externos de fuente.
- El snapshot mínimo se identifica mediante `recovery_scope`, `INCOMPLETE`/`FAILED`.
  Conserva definiciones de grupos pendientes, pero no reconstruye sus resultados
  ni TC. No es un reporte completo para el renderer HTML. No se crea
  `QC_COMPLETE.json`; códigos CLI 2 para fallo y 130 para cancelación.
- Si el informe ya estaba construido, se conserva la recuperación existente con
  sus resultados y alcance. La escritura sigue siendo best effort: disco lleno
  o permisos pueden impedirla y se informa en consola.

Se añaden 14 casos en `tests/test_recovery_boundaries.py`: errores antes del informe,
conservación entre programas y antes de su evaluación, cancelación por token y
KeyboardInterrupt al calcular el hash del primer/segundo archivo, protección de
fuente, ausencia de mutación y fallo de escritura de recuperación. Fixtures
sintéticos con verificación de SHA-256, tamaño y mtime; sin material de producción.

Validación ejecutada en macOS 26.5.2 ARM64, Python 3.14.8, FFmpeg 9.0.2:
**104 focalizadas aprobadas** (13,30 s), incluidas las de GUI offscreen;
suite completa **781 aprobadas, 0 fallidas, 8 omitidas** (46,98 s). Las omisiones
son del runtime Essentia opcional sin `XQC_ESSENTIA_PYTHON`. Se observaron los
fallos de regresión antes de corregirlos; no se regeneraron golden fixtures.
`git diff --check` sin errores. CI remota, GUI manual y DAW no verificadas.

Comandos de validación desde `audio-delivery-qc/`:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_recovery_boundaries.py tests/test_virtual_reports.py tests/test_hotfix_acceptance.py tests/test_operational_robustness.py tests/test_process_cancellation.py tests/test_policy_separation.py tests/test_virtual_gui.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

No se cambian detectores, umbrales, presets ni cálculos acústicos. La protección
de fuentes durante snippets y la decisión sobre cobertura truncada siguen
pendientes; no forman parte de esta corrección. No se instalaron dependencias,
crearon ramas ni realizaron commits/pushes. El cambio previo de bit depth y el
mapa local se conservan; el mapa no se ha actualizado.
