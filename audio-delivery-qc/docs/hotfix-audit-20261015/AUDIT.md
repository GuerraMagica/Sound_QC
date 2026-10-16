# Auditoría de robustez — 2026-10-15

> Publicación en GitHub: 2026-10-16. Se publica la auditoría realizada el día anterior, sus scripts y el resultado de seguridad. Los cinco defectos siguen pendientes; este commit no implementa el HOTFIX. Los WAV, informes individuales y logs generados permanecen locales. Las rutas `reports/hotfix-audit-20261015` del texto documentan la ejecución original.
>
> Para reproducir desde `audio-delivery-qc` con los scripts publicados, elegir un directorio de salida nuevo:
>
> ```sh
> .venv/bin/python docs/hotfix-audit-20261015/probe.py /private/tmp/audio-qc-review-NEW
> .venv/bin/python docs/hotfix-audit-20261015/probe_shutdown.py /private/tmp/audio-qc-review-NEW
> ```
>
> En otros sistemas, sustituir `/private/tmp` por un directorio temporal local. `audit-requirements.txt` es un inventario histórico de la auditoría, no un archivo de instalación de la aplicación.

**Veredicto: FAIL respecto a los criterios del documento HOTFIX.** La recuperación de CI (H1) está verificada. H2–H5 todavía tienen problemas reproducibles. Este es un informe de revisión solicitado por el usuario, no una implementación del documento adjunto.

Código revisado: `fdfb001e72d0c727778f151d60b0046a50d39161`, rama `main`. El documento parte de `2e213732`; se revisó el estado actual, que ya incorpora las correcciones de CI posteriores. Ningún archivo de producción, test versionado, dependencia, umbral o fixture de referencia fue modificado durante esta auditoría. Los únicos archivos nuevos son los artefactos locales ignorados de este directorio.

## Hallazgos, en orden de prioridad

### 1. P1 — Un valor de Integrated inválido puede conservar un resultado anterior y producir PASS

Referencia: `src/audio_qc/loudness.py:29-33`, `:49-63`.

El parser actualiza `values` únicamente cuando un número es finito. Si recibe `lavfi.r128.I=-23.000` y después `lavfi.r128.I=nan`, conserva −23.000. La presencia de `Summary:` basta para habilitar el resultado; no queda constancia del último dato inválido.

Reproducción: flujo EBU controlado con esos dos valores, Summary y True Peak −20.0. Se mantuvieron reales la lectura del WAV, análisis de muestras, evaluación de política y generación JSON/HTML. Resultado: **PASS, salida CLI 0, Integrated −23.0**. La salida inválida no se distingue de una medición correcta. No se afirma que el FFmpeg instalado produzca espontáneamente ese flujo: se inyecta para verificar el requisito de tolerancia a salida malformada.

Corrección necesaria: registrar validez y completitud de las métricas; no presentar un valor anterior como medición final válida cuando la salida posterior es inválida. Diferenciar los valores legítimamente indefinidos de la salida corrupta. No cambiar la fórmula EBU ni los umbrales.

### 2. P1 — Fallo/timeout de medición obligatoria termina con salida de éxito

Referencias: `src/audio_qc/scanner.py:109-113`, `src/audio_qc/rules.py:31-49`, `src/audio_qc/cli.py:139`.

El scanner convierte ToolError/OSError en el texto `loudness_unavailable`. La política transforma cualquier ausencia de Integrated/True Peak en WARNING. La CLI devuelve 0 para WARNING. Falta un estado independiente de ejecución/medición.

Con BROADCAST_EBU_R128, se reprodujeron cuatro variantes: error de FFmpeg, timeout, resumen ausente y Integrated ausente en un resumen aparentemente terminado. Todas produjeron **WARNING y salida 0**. Un archivo realmente silencioso también produce WARNING/0; los estados de éxito/indefinido/error no se representan explícitamente en JSON/HTML.

Esto no es un PASS literal en las cuatro variantes: es un **éxito operativo de CLI con evaluación obligatoria incompleta**. Puede engañar a automatizaciones que comprueban el código de salida.

Corrección necesaria: resultado técnico explícito, evaluación de obligatoriedad en la política y ejecución incompleta con código 2 (ya existente) cuando corresponda. Mantener disponible el análisis de muestras que sí terminó y el tratamiento legítimo del silencio.

### 3. P1 — Error de exportación de evidencia se clasifica como incumplimiento del audio

Referencias: `src/audio_qc/cli.py:114-125`, `src/audio_qc/snippets.py:8-9` y bloque de excepciones del exportador.

Inspección y exportación comparten un catch que añade `unexpected_inspection_error` con FAIL. La creación de `defect_snippets` queda fuera del catch local del exportador. Por ello un permiso denegado al preparar evidencia puede marcar el archivo como FAIL aunque sus mediciones cumplan la especificación.

El mismo WAV con un candidato de click da WARNING/0 sin exportación. Con PermissionError o RuntimeError inyectados en la exportación, pasa a **FAIL/1**, manteniendo exactamente Integrated −23.007 y True Peak −4.4. No hay un incumplimiento acústico nuevo. El ToolError gestionado dentro del exportador produce WARNING/0, sin un estado explícito de evidencia incompleta.

Corrección necesaria: conservar los hallazgos acústicos y registrar el error de evidencia en diagnósticos operativos. Declarar si la evidencia solicitada es obligatoria u opcional para elegir PARTIAL o COMPLETED_WITH_WARNINGS. No cambiar el estado acústico por el error de escritura.

### 4. P2 — `error_saved()` depende del separador POSIX

Referencia: `src/audio_qc/diagnostics.py:71-73`.

`endswith('/error.log')` devuelve False para `C:\reports\error.log`, incluso con stream abierto y sin error. La prueba controlada confirma ese falso negativo.

Corrección necesaria: identificar el handler por referencia/nombre estable. La alternativa del documento `Path(...).name` funciona con rutas nativas del SO, pero **en macOS/Linux no interpreta por sí sola una cadena con separadores Windows**; una prueba de representaciones Windows requiere PureWindowsPath o, preferiblemente, evitar inferir identidad desde la ruta.

No se ejecutó un entorno Windows nativo. El fallo de la condición se reprodujo con una representación Windows.

### 5. P2 — Un fallo de cierre del log puede perder su aviso de consola

Referencia: `src/audio_qc/diagnostics.py:75-81`.

`close()` retira primero los handlers de stdout/stderr. Si después falla el cierre de un handler de archivo, intenta avisar mediante el mismo logger, que ya no tiene esos handlers de consola.

Con OSError controlado al cerrar scan.log, `stderr` quedó vacío; el aviso solo apareció en el propio archivo de log. No se cumple el aviso de consola de mejor esfuerzo para fallos tardíos.

Corrección necesaria: mantener la consola hasta terminar el cierre de archivos o avisar directamente a stderr sin reentrar en los handlers de archivo. Los informes ya finalizados deben seguir siendo instantáneas: no hace falta reescribirlos por este error opcional.

## H1 — CI realmente verificada

[Run 38810075928](https://github.com/GuerraMagica/Sound_QC/actions/runs/38810075928), commit revisado:

| Trabajo | Estado remoto verificado | Resultado del registro |
|---|---|---|
| test (3.11) | PASS | 496 passed in 35.51s |
| test (3.14) | PASS | 496 passed in 33.91s |
| dependency-audit | PASS | No known vulnerabilities found |

El estado de cada trabajo se volvió a consultar en esta auditoría. Los tiempos proceden de los logs descargados de esa ejecución durante la reparación anterior; no se inició una ejecución remota nueva porque el código no cambió. Ubuntu 24.04, Qt offscreen, FFmpeg 6.1.1. La corrección previa conserva todos los tests y la auditoría estricta.

La evidencia previa sitúa los fallos originales en tres puntos: combinación `--skip-editable --strict`, asignación de layout con aformat en FFmpeg 6 y destrucción de objetos Qt al finalizar el intérprete. No demuestra un defecto de NumPy. El éxito de CI demuestra que esa ejecución terminó correctamente, no que los nuevos criterios H2–H5 estén cubiertos.

## Validación ejecutada en esta revisión

Entorno local: macOS 26.5.2 ARM64, Python 3.14.8, FFmpeg/ffprobe 9.0.2.

Desde la carpeta `audio-delivery-qc`:

```sh
.venv/bin/python -m pytest -q tests/test_operational_robustness.py tests/test_loudness.py tests/test_policy_baseline.py tests/test_gui.py tests/test_custom_gui.py
# 62 passed in 5.76s; sin fallos ni skips

.venv/bin/python -m pytest -q
# 496 passed in 16.66s; sin fallos ni skips
```

Incluye GUI offscreen con workers CLI reales, cancelación, fallos de disco/permisos, preservación de muestras de evidencia y referencias de medición. No se hizo una nueva revisión visual interactiva de la GUI.

Auditoría adicional: `pip check` sin dependencias rotas; pip-audit en entorno separado sobre 39 versiones instaladas, **salida 0, ninguna vulnerabilidad conocida**. No se instaló ni actualizó nada en el entorno de la aplicación. La lista incluye las dependencias de la aplicación y del propio auditor. No cubre vulnerabilidades de bibliotecas externas de FFmpeg ni garantiza ausencia de vulnerabilidades desconocidas.

```sh
PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" /private/tmp/audio-qc-audit-env/bin/python -m pip check
PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" /private/tmp/audio-qc-audit-env/bin/python -m pip list --format=freeze --exclude audio-delivery-qc > reports/hotfix-audit-20261015/audit-requirements.txt
/private/tmp/audio-qc-audit-env/bin/python -m pip_audit --strict --no-deps --disable-pip -r reports/hotfix-audit-20261015/audit-requirements.txt --cache-dir /private/tmp/audio-qc-audit-cache --format json --output reports/hotfix-audit-20261015/pip-audit.json
```

Resultados: `audit-requirements.txt`, `pip-audit.json`.

## Reproducción de fallos controlados

```sh
.venv/bin/python reports/hotfix-audit-20261015/probe.py /private/tmp/audio-qc-hotfix-review-NEW
```

Elegir una carpeta NUEVA: el script no sobrescribe una existente. Crea tres WAV sintéticos y ejecuta 16 casos de CLI. Inyecta fallos en interfaces específicas sin alterar el código de producción. Las pruebas de timeout de este script inyectan ToolError, no esperan una expiración real. Los tests del repositorio cubren adicionalmente la gestión real de procesos.

| Caso | Estado informe | Salida CLI |
|---|---|---:|
| Señal válida | PASS | 0 |
| Silencio digital | WARNING | 0 |
| Error FFmpeg | WARNING | 0 |
| Timeout FFmpeg | WARNING | 0 |
| Sin resumen | WARNING | 0 |
| Sin Integrated | WARNING | 0 |
| Integrated válido seguido de nan | PASS | 0 |
| Click, sin fallo operativo | WARNING | 0 |
| Permiso denegado en evidencia | FAIL | 1 |
| Error inesperado en evidencia | FAIL | 1 |
| Error FFmpeg al extraer evidencia | WARNING | 0 |
| Fallo de log antes de informes | WARNING (archivo PASS) | 0 |
| Fallo de log después de informes | PASS | 0 |
| Disco lleno al escribir informes | Sin informe | 2 |
| Permiso denegado al escribir informes | Sin informe | 2 |
| Cancelación | Sin informe | 130 |

`artifacts/observations.json` conserva valores, checks, estados y stderr. Cada caso tiene JSON, HTML y consola cuando la operación permite generar informes. La prueba de cierre se conserva separadamente en `probe_shutdown.py` y `artifacts/shutdown_observation.json`.

Los JSON y HTML de los casos que se completaron muestran el mismo estado general. **Consistencia entre formatos no implica que el estado sea correcto**. Los fallos de log conocidos antes de finalizar aparecen en ambos. El fallo inyectado después de escribir los informes aparece en consola, no retroactivamente en los informes; ese comportamiento puede ser correcto si se documenta. El fallo de cierre descrito en el hallazgo 5 sí pierde el aviso de consola.

Los tres WAV conservaron SHA-256, tamaño y mtime_ns exactamente; fingerprints antes/después en observations.json. No se usó ni modificó audio del usuario. No se modificaron algoritmos, umbrales, BWF ni golden fixtures. La comparación con golden que permite un ULP ya existía antes de esta auditoría y no se amplió.

## Cobertura que debe cambiar antes de aceptar el HOTFIX

Los tests actuales `test_failed_ffmpeg_summary_never_becomes_valid_measurement` y `test_per_file_error_continues_and_preserves_previous_measurements` exigen respectivamente WARNING para fallo FFmpeg y FAIL/1 para fallo de evidencia. Pasan, pero no representan las nuevas expectativas H2/H3. Hay que actualizar esas expectativas con intención documentada y añadir casos de resultado inválido/ausente; mantener sus comprobaciones de preservación de mediciones y continuidad.

El documento también necesita concretar la obligatoriedad por métrica: Integrated, True Peak, LRA, modos report-only/desactivados y evidencia solicitada no tienen necesariamente los mismos requisitos. Si hay un incumplimiento acústico válido y otra medición falla, se deben conservar ambos hechos y dar precedencia operativa al análisis incompleto en la salida CLI. No basta añadir un único enum que vuelva a mezclar los dos ejes.

H1: PASS. H2 y H3: FAIL, bloqueantes. H4: FAIL, defecto reproducido. H5: parcial, fallo de cierre reproducido y política de eventos tardíos pendiente de explicitar. H6/H7: la regresión existente pasa; no equivale a una validación completa de un HOTFIX aún no implementado. No se comenzó M5/M6.
