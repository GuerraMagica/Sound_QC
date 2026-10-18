# XQC — estado vigente

Actualización documental: **18 de octubre de 2026**. Este documento sintetiza la
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
  [audio_qc](src/audio_qc/__init__.py); informes JSON schema **4**.
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

**Actual:** inspección estática de código, configuración y documentos; comprobación
local de baseline/Git y validación documental de rutas, alcance y diff. La
publicación documental incluye verificación de referencias Git remotas; no se han
ejecutado tests locales de aplicación ni procesamiento local de audio, ni se ha
revalidado la CI histórica.

## 6. Limitaciones conocidas

- M5 **no mide Integrated LUFS, LRA ni True Peak del programa combinado**. Los
  resultados mono son diagnósticos físicos, no loudness del 5.1; programme compliance
  permanece `NOT_EVALUATED`. `VALID` solo expresa validez estructural/alineación.
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
El hotfix documenta aceptación operativa A–F. No se repitió ninguna en esta tarea.

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
  Mantener schema 4 y compatibilidad de CSV; cambios requieren evaluación explícita.
- Separar SUCCESS/UNAVAILABLE/ERROR, ejecución y cumplimiento acústico. El marcador
  `QC_COMPLETE.json` confirma entrega del reporte, no un PASS del audio.

## 9. Trabajo pendiente

| Milestone / decisión | Estado y autorización |
| --- | --- |
| M5 y seguimiento de fiabilidad | Implementado y aceptado por el usuario; validaciones históricas arriba |
| Documentación V1.0 | Implementada en AGENTS, PROJECT_STATE y enlace README; sin cambios funcionales |
| Tag de baseline M5 | `m5-accepted`: anotado, creado y publicado sobre el commit aceptado |
| M6: medición multicanal virtual | Siguiente milestone previsto; NO INICIADO, no implementado ni autorizado por esta tarea |
| M7: clicks/ticks | Posterior a M6; mejorar precisión/reducir falsos positivos sin perder defectos reales; no implementado ni autorizado |
| M8: UX/reportes/manual | Posterior a M7; simplificación para facility, no implementado ni autorizado |

M6 prevé medir LUFS/LRA/dBTP de WAV mono sincronizados sin generar masters
interleaved completos, contrastando con un interleaved de referencia dentro de
tolerancias verificadas. Su aceptación futura requiere pruebas automatizadas,
regresión, integridad, validación profesional y aprobación expresa del usuario.
El usuario declara una **especificación externa preparada**, pendiente de incorporar
o referenciar formalmente: no se ha localizado como especificación M6 en los
documentos del repositorio inspeccionados; no se inventa una ruta ni se incorpora.

## 10. Próximo objetivo aprobado

**Pendiente de definición y aprobación del usuario** para el siguiente desarrollo
funcional. M6 es el siguiente milestone previsto y todavía no está implementado.
El ajuste documental V1.0 no autoriza ningún desarrollo funcional nuevo.

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
