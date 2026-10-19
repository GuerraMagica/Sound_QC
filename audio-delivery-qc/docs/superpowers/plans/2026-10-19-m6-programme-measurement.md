# M6 Virtual Multichannel Programme Measurement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task if the proposed inline execution is approved. Steps use checkbox (`- [ ]`) syntax for tracking. No automatic commits, worktrees or delegation.

**Goal:** medir programas stereo/5.1 multiple-mono mediante un stream virtual verificable, aplicar la política existente y presentar resultados sin modificar fuentes.

**Architecture:** conservar la construcción de grupos e issues M5; añadir elegibilidad y medición del programa en la capa de medición. Reutilizar parser EBU y evaluador de niveles; interfaces y reporting consumen resultados estructurados. Cancelación cooperativa comparte el ciclo de vida de los procesos existentes.

**Tech Stack:** Python ≥3.11, FFmpeg/ffprobe existentes, NumPy, PyYAML, PySide6 y pytest del entorno actual; sin dependencias nuevas.

**Spec:** [M6_DESIGN.md](../../M6_DESIGN.md), aprobado el 19/10/2026. Plan y rama local aprobados por el usuario. La evidencia de ejecución está en M6_VALIDATION; este documento describe criterios, no sustituye los resultados.

## Global Constraints

- Baseline funcional `d339b70026a1941ee732a5eb7962581aab0ad6c7`, tag `m5-accepted`; HEAD documental observado `68970dee0cee2d213bfc2e4c16e9b8e218771b8c`.
- Fuentes estrictamente read-only; evidencia/reportes en destinos nuevos. Solo fixtures sintéticos para esta ejecución.
- `sample_index` y TimeReference enteros permanecen autoritativos; TC solo navegación.
- Sin cambios a detectores, umbrales, grouping, caps, orden de canales ni tolerancias M5.
- Stereo: L→FL, R→FR. 5.1: L→FL, R→FR, C→FC, LFE→LFE, Ls→SL, Rs→SR; layout explícito `5.1(side)`.
- Sin resampling de frecuencia, padding, trimming, delays, amix, normalización, master productivo ni inferencia de offsets/rollover.
- BWF ausente requiere `common_file_start` explícito; referencias presentes contradictorias siempre impiden M6.
- SUCCESS / UNAVAILABLE / ERROR por métrica; errores operativos separados del incumplimiento. LRA report-only.
- JSON schema 5, conservación de provenance y columnas CSV existentes; históricos intactos.
- Sin M7/M8, click detection nuevo, --compare, Docker, concurrencia, instalaciones o conexiones externas.
- Aprobación de este plan no autoriza commits, tags, pushes ni publicación. Se solicita por separado en la misma revisión crear **solo la rama local `codex/m6-programme-measurement`**, desde el HEAD documental comprobado, conservando ambos documentos; sin worktree adicional.

## Review Focus

1. Cambio de fuente entre inspección física y pasada virtual: invalidar medidas, conservar diagnóstico y nunca certificar PASS (tarea 3).
2. Cancelación sin salida del hijo o durante un fallo simultáneo: recoger proceso y distinguir cancelación de error acústico (tareas 2 y 7).
3. PCM mixto y canal LFE dominante: probar identidad por rol, loudness excluye LFE, TP lo incluye (tareas 1 y 4).
4. Grupo inválido con miembros identificables: no sustituir medición de programa por seis decisiones mono (tareas 5 y 6).
5. Informe parcialmente escrito o resultados de nivel correctos con defectos truncados: no confundir entrega, niveles y cobertura (tareas 6 y 8).

## Organización y ejecución

Todas las rutas siguientes son relativas a `audio-delivery-qc/`. Conservar estilo y estructuras actuales; no reestructurar módulos ajenos.
Ejecución propuesta: secuencial en esta sesión, con revisión del diff y evidencia al cerrar cada tarea. Las interfaces siguientes son contratos propuestos; un cambio local de nombre es admisible si se actualizan todos sus consumidores. Un cambio de alcance o semántica exige consulta.

Las tareas siguen RED → implementación mínima → GREEN. Registrar el fallo esperado de cada prueba nueva; no considerar un error de entorno como RED válido. Los comandos de abajo son **pendientes**, no resultados. Ejecutarlos desde el proyecto con `.venv/bin/python`; `QT_QPA_PLATFORM=offscreen` para automatización GUI. No repetir una suite que ya pasó salvo cambios posteriores relevantes.

### Tarea 1 — Referencias PCM y caracterización de la baseline

**Files:** crear `tests/m6_fixtures.py`, `tests/test_programme_pcm.py`; reutilizar `src/audio_qc/synthetic.py` sin modificarlo si basta. Inspeccionar `tests/test_loudness.py`, `test_policy_baseline.py` y `test_hotfix_acceptance.py`.

**Interfaces:** fixture helper `make_programme_fixture(root: Path, *, layout: str, seconds: int = 12, case: str = "asymmetric", time_reference: int | None = 172800000) -> dict`, con claves `members`, `reference`, `manifest`, `sample_rate`, `sample_count`, `pcm_by_role`. 48 kHz/24-bit por defecto; fuentes y referencia parten de los mismos enteros cuantizados. Fixtures largos de tarea 8 usan generación por bloques, sin `pcm_by_role` completo.

- [x] Confirmar Git, baseline y entorno local; crear la rama propuesta **solo si fue aprobada**, sin reset, checkout de baseline antigua ni descarte de documentos. Si existe, verificar su historia antes de reutilizarla.
- [x] Registrar versiones Python/FFmpeg/Qt y ejecutar `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` antes de editar código funcional. Conservar números reales; 627 es histórico, no resultado esperado obligatorio.
- [x] Escribir `test_reference_roles_and_pcm`: verificar 576000 frames para 12 s, dos/seis canales, máscara stereo/`5.1(side)` y PCM exacto por rol; fixtures con amplitudes/frecuencias distintas, LFE solo y niveles variables para LRA. Añadir `test_reference_integrity_snapshot` con SHA-256, size y mtime_ns.
- [x] Ejecutar `.venv/bin/python -m pytest -q tests/test_programme_pcm.py`, implementar el helper y repetir hasta GREEN. Capturar medidas interleaved de la baseline para comparar en tarea 8; no actualizar goldens existentes.

### Tarea 2 — Cancelación segura de procesos y fases

**Files:** modificar `src/audio_qc/process.py`, `scanner.py`, `samples.py`, `metadata.py`, `loudness.py`, `snippets.py`, `hashing.py`; crear `tests/test_process_cancellation.py`.

**Interfaces:** en `process.py`, `CancellationToken.cancel() -> None`, `raise_if_cancelled() -> None`, `cancelled: bool`; `ScanCancelled(KeyboardInterrupt)` evita que los `except Exception` actuales fabriquen errores de medición. Añadir `cancel: CancellationToken | None = None` como keyword opcional a `stream_process` y a las funciones que realizan esas fases; defaults conservan llamadas existentes. El token se pasa explícitamente, no mediante estado global.

- [x] Escribir `test_cancel_blocked_reader_reaps_child`, `test_cancel_before_spawn`, `test_cancel_after_exit_is_idempotent`, `test_timeout_remains_tool_error`, `test_parser_failure_remains_tool_error`, `test_cancel_hash_and_sample_loop`. Usar hijos Python sintéticos y deadlines acotados; afirmar PID terminado, pipes cerradas y ausencia de falso SUCCESS.
- [x] Ejecutar `.venv/bin/python -m pytest -q tests/test_process_cancellation.py` y registrar RED.
- [x] Integrar vigilancia de cancelación durante lecturas bloqueantes: terminate, gracia de 2 s, kill si procede, wait y limpieza en finally. Evitar carrera timer/proceso terminado. Consultar token entre bloques/fases; si se observó cancelación solicitada antes de finalizar el proceso, propagar `ScanCancelled` en vez de clasificar su exit como defecto.
- [x] Repetir focalizadas y ejecutar `.venv/bin/python -m pytest -q tests/test_operational_robustness.py tests/test_hotfix_acceptance.py tests/test_loudness.py`.

### Tarea 3 — Elegibilidad y resultado de medición del programa

**Files:** crear `src/audio_qc/programme_measurement.py`, `tests/test_programme_measurement.py`; consumir `programme.py`, `measurement.py`, `models.py` sin alterar grouping.

**Interfaces:** definir en el módulo nuevo `ProgrammeInput` (group_id, layout, ordered_members: tuple de pares rol/Path, sample_rate, sample_count, alignment, source_signatures), `ProgrammeEligibility` (eligible, reasons, warnings, input opcional) y `ProgrammeMeasurement` (state, method, measurements, measurement_outcomes, operational_diagnostics, provenance). Usar `MeasurementOutcome` y `OperationalDiagnostic` existentes; state de fase `DISABLED | NOT_EVALUATED | SUCCESS | ERROR`, distinto del outcome por métrica.

`programme_eligibility(group: dict, files: list[AudioFile], signatures: dict[str, tuple[int, int, int]]) -> ProgrammeEligibility` es puro. Firmas tomadas inmediatamente antes de inspeccionar cada fuente por el orquestador. `verify_programme_sources(inputs: ProgrammeInput) -> None` compara stat y lanza `ToolError` con fuente concreta si cambió/no existe.

- [x] Escribir `test_eligibility_matrix`: M5 VALID, mono PCM, roles/paths únicos, samples completos, rates/counts iguales positivos; referencias 0 y >2**53 exactas; BWF iguales, ausentes con modo explícito, ausentes con auto, mixtos, contradictorios incluso explícitos, corruptos y no finitos. Comprobar no mutación de groups/AudioFile. Caps no impiden niveles.
- [x] Escribir `test_source_changed_between_passes` y `test_source_changed_during_pass`: cambio size/mtime/inode y borrado deben impedir certificación; no modificar fixtures de integridad, usar copias desechables dedicadas a inyección.
- [x] Ejecutar `.venv/bin/python -m pytest -q tests/test_programme_measurement.py`, registrar RED e implementar criterios exactos del diseño, sin aplicar umbrales ni reparar alineación.
- [x] Repetir y ejecutar `.venv/bin/python -m pytest -q tests/test_programme.py tests/test_m5_followup.py`.

### Tarea 4 — Entrada virtual y backend EBU compartido

**Files:** modificar `src/audio_qc/loudness.py`, `programme_measurement.py`; ampliar `test_programme_pcm.py`, `test_programme_measurement.py`; crear `tests/test_virtual_loudness.py`.

**Interfaces:** `virtual_input_args(inputs: ProgrammeInput) -> tuple[list[str], str]` devuelve argumentos locales de entrada y grafo join con mapa explícito. `measure_programme(inputs: ProgrammeInput, requirements: MeasurementRequirements, progress=None, *, cancel=None) -> ProgrammeMeasurement` comprueba firmas antes/después, ejecuta una pasada o devuelve DISABLED. En `loudness.py`, extraer `run_loudness(args: list[str], duration: float | None, progress=None, *, timeout=None, cancel=None) -> dict`; la ruta física lo reutiliza conservando filtros/semántica. No copiar el parser.

- [x] Escribir `test_join_pcm_matches_reference` para stereo/5.1, manifest desordenado, roles aislados, 16/24-bit mixtos y PCM float finito compatible. Comparar salida por bloques con referencia independiente; nunca derivar mapa esperado del helper productivo.
- [x] Escribir `test_virtual_metrics_match_interleaved`, `test_lfe_excluded_from_loudness`, `test_lfe_included_in_true_peak`, `test_silence_and_below_gate_unavailable`, `test_missing_metrics_error`, `test_ffmpeg_failure_timeout_and_malformed_output`. Comprobar I/LRA/TP con techo 0,1 y registrar delta real; usar señales variables para LRA y LFE dominante con programa activo para TP.
- [x] Ejecutar `.venv/bin/python -m pytest -q tests/test_programme_pcm.py tests/test_virtual_loudness.py` y registrar RED.
- [x] Construir entradas con protocolo local/guessing desactivado por entrada, mapa rol→input explícito y `join`, seguido del filtro EBU actual. Medir longitud exacta del stream con contabilidad acotada de `nb_samples` antes de EBU (p.ej. `ashowinfo` identificado), sin retener frames; fin correcto con número inesperado produce ERROR. El comando productivo termina en null; solo tests capturan PCM. No asumir duración de updates de 100 ms como sample count.
- [x] Ejecutar focalizadas y `.venv/bin/python -m pytest -q tests/test_loudness.py tests/test_scanner_rules.py tests/test_policy_baseline.py`; demostrar que la ruta física conserva sus resultados. Si backend no garantiza mapa/PCM, detener aceptación y diagnosticar; no ampliar tolerancias.

### Tarea 5 — Scope de política y orquestación CLI

**Files:** modificar `src/audio_qc/rules.py`, `measurement.py`, `scanner.py`, `cli.py`; crear `tests/test_programme_policy.py`, `tests/test_virtual_cli.py`.

**Interfaces:** `assess_file(..., *, level_scope: str = "FILE")` y `evaluate_file_policy(..., *, level_scope="FILE")` admiten `PROGRAMME_MEMBER`. `inspect_file(..., *, level_scope="FILE", cancel=None)` conserva API previa. Añadir `levels_required: bool = True` a `MeasurementRequirements`; el orquestador lo fija False solo para diagnósticos mono agrupados, manteniendo el scheduling EBU. `assess_programme(measurement: ProgrammeMeasurement, policy: dict) -> list[Check]` en `rules.py` invoca `evaluate_level_policy` sin duplicar comparaciones; NOT_EVALUATED/ERROR solicitados generan INCOMPLETE, DISABLED solo INFO.

- [x] Escribir `test_programme_target_evaluated_once`, `test_invalid_group_does_not_fall_back_to_mono_targets`, `test_mono_error_retained_as_optional_diagnostic`, `test_ungrouped_mandatory_error_still_incomplete`, `test_true_peak_only_and_disabled`, `test_inputs_not_mutated`. Una fuente declarada no pierde defectos/checks técnicos; lectura fallida sigue siendo obligatoria. Métricas mono ERROR se conservan aunque no bloqueen medida de programa válida.
- [x] Escribir `test_cli_scopes_and_exit_codes`: nivel conforme 0, incumplimiento 1, medición requerida ausente/fallida 2, cancelación 130; comprobar precedencia operativa y valores efectivos CUSTOM. Grupos ambiguos no eligen propietario arbitrario ni reciben PASS de programa.
- [x] Ejecutar `.venv/bin/python -m pytest -q tests/test_programme_policy.py tests/test_virtual_cli.py`, registrar RED e integrar: membership antes de inspección, firmas por fuente, una inspección por archivo, M5 build sin cambios, elegibilidad/pasada/política por grupo. No releer audio para construir grupos. Mantener diagnósticos mono y extra pasada de programa explícitos en logs.
- [x] Repetir y ejecutar `.venv/bin/python -m pytest -q tests/test_policy.py tests/test_policy_separation.py tests/test_custom_policy.py tests/test_custom_config.py tests/test_operational_robustness.py`.

### Tarea 6 — Schema 5 e informes consistentes

**Files:** modificar `src/audio_qc/reports/__init__.py`, `programme_report.py`, `html_report.py`, `cli.py`; crear `tests/test_virtual_reports.py`. CSV existentes conservan columnas y formas de filas.

**Interfaces:** adjuntar en copia del dict M5 `programme_measurement` (serialización del resultado), `level_checks`, `programme_compliance` y `level_scope`. `build_report` consume estos campos; `programme_timecodes` ya no sustituye el resultado por NOT_EVALUATED fijo. Nivel global agrega checks físicos técnicos y del programa; `compliance_scope` documenta `PHYSICAL_FILES_AND_PROGRAMME_LEVELS` con grupos y `PHYSICAL_FILES` sin ellos.

- [x] Escribir `test_schema5_provenance_and_counts`, `test_json_html_cli_agree`, `test_caps_visible_with_successful_loudness`, `test_invalid_disabled_and_unavailable_not_pass`, `test_group_diagnostics_affect_execution`, `test_report_failure_no_complete_marker`, `test_legacy_csv_columns_and_snippet_links`. JSON conserva medidas mono, muestras, TC y eventos exactos; enlaces relativos escapados mantienen target/rel. Programa silencioso WARNING, nunca medición cero fabricada.
- [x] Ejecutar `.venv/bin/python -m pytest -q tests/test_virtual_reports.py`, registrar RED e implementar resumen I/LRA/TP, método, elegibilidad, estado de ejecución, política y coverage separados. Errores requeridos del programa participan en ejecución global; conservar los opcionales. Resumen de archivos sigue siendo recuento físico; añadir recuento de programas sin sumarlos como defectos únicos.
- [x] Repetir y ejecutar `.venv/bin/python -m pytest -q tests/test_custom_reports.py tests/test_reports_cli.py tests/test_consolidation_reports.py tests/test_defect_csv.py tests/test_issue_evidence.py`. Cambiar expectativas schema/scope solo con justificación vinculada a este diseño; no borrar pruebas del hotfix ni checks de integridad.

### Tarea 7 — GUI, snapshot y cancelación de extremo a extremo

**Files:** modificar `src/audio_qc/gui_window.py`, `cli.py`; crear `tests/test_virtual_gui.py`; reutilizar fixtures Qt de `tests/conftest.py` sin debilitarlos.

**Interfaces:** `QCWindow.cancel_qc() -> None` envía una vez `CANCEL\n` al QProcess. Flag interno CLI `--gui-control-stdin`, oculto de ayuda pública, activa lector de líneas acotado que cancela el token. EOF por sí solo no cancela. Ctrl+C señala el mismo token/limpieza. Sin sockets, threads de análisis Qt nuevos ni control por archivos de audio.

- [x] Escribir `test_cancel_button_states`, `test_gui_cli_snapshot_equivalence`, `test_cancel_real_virtual_child`, `test_cancel_before_virtual_pass`, `test_repeat_cancel_and_close_while_cancelling`. Afirmar hijo terminado, salida 130, controles reactivados, sin QC_COMPLETE y sin anuncio de entrega completa. La GUI no mata solo al padre como ruta normal de cancelación.
- [x] Ejecutar `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_virtual_gui.py`, registrar RED e integrar botón mínimo, estado Cancelando/Cancelado y resumen de programa. Mantener snapshot inmutable de configuración/membership durante ejecución.
- [x] Repetir y ejecutar `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_gui.py tests/test_custom_gui.py tests/test_programme_gui.py tests/test_m5_followup_gui.py`. Validación real QProcess no se sustituye por mocks de UI.

### Tarea 8 — Aceptación reproducible AC01–AC18 y regresión completa

**Files:** crear `scripts/verify_m6.py`, `tests/test_m6_acceptance.py`; revisar `scripts/verify_m5.py` para documentar aserciones históricas de scope que M6 sustituye, sin reescribir resultados históricos.

**Interfaces:** `verify_m6.py --output NEW_DIRECTORY` crea solo fixtures/evidencia nuevos y rechaza destinos existentes. Emite `acceptance.json`: versiones, comandos, códigos, estados AC, diferencias métricas/PCM, firmas, PIDs observados, memoria, rutas de evidencia y limitaciones. `--memory` añade casos 30/600 s con escritura por bloques y muestreo RSS padre/hijo vía herramientas del SO, sin dependencia nueva. Nunca ejecuta auto-install ni conexiones externas.

- [x] Escribir `test_acceptance_output_is_new_and_sources_unchanged`, `test_ac_matrix_is_complete`, `test_cancel_and_export_errors_preserve_completed_facts`; comprobar escenarios conforme, incumplimiento, fallo FFmpeg, evidencia fallida, silencio, informe fallido y cancelación. Diseñar snapshots de PCM/medidas físicas comparables a tarea 1, excluyendo solo campos de scope/schema expresamente cambiados.
- [x] Ejecutar `.venv/bin/python -m pytest -q tests/test_m6_acceptance.py`, registrar RED e implementar runner que utiliza rutas productivas CLI y guarda evidencia real; sin consignar expectativas como resultados.
- [x] Ejecutar focalizadas nuevas y después `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`. Registrar passed/failed/skipped; investigar cada fallo y repetir solo pruebas afectadas, luego suite final tras últimas correcciones. No omitir tests existentes para aprobar.
- [x] Ejecutar `.venv/bin/python scripts/verify_m6.py --output /tmp/xqc-m6-acceptance-UNIQUE --memory` sustituyendo UNIQUE por un identificador nuevo. AC01–06: PCM/métricas/mapa/LFE; AC07–10: elegibilidad; AC11–12: política; AC13–14: física/CLI/GUI; AC15: cancelación; AC16: integridad; AC17: memoria; AC18: silencio. AC17 crecimiento ≤64 MiB por proceso tras calentamiento; capturar curvas/picos, investigar exceso y no ajustar techo para pasar.
- [x] Ejecutar `.venv/bin/python scripts/verify_hotfix_release.py --output /tmp/xqc-m6-hotfix-UNIQUE` en destino nuevo. Revisar regresión M5/evidencia/timecode/descubrimiento dentro de suite completa; no forzar el script M5 histórico a aceptar semántica nueva sin documentarla.
- [ ] Validar manualmente GUI con fixtures sintéticos y cancelar pasada virtual; separar automatización offscreen de inspección visual. Comprobar macOS y Linux/Python 3.11/3.14 donde exista entorno autorizado. Si Linux/CI no está disponible, declarar ese criterio pendiente: no publicar ni acceder a GitHub implícitamente para obtenerlo.

### Tarea 9 — Documentación de resultados y revisión final

**Files:** actualizar `PROJECT_STATE.md`, `README.md`, `docs/PROGRAMME_GROUPS.md`; crear `docs/M6_VALIDATION.md`. Conservar [diseño](../../M6_DESIGN.md) y este plan como decisiones, sin convertirlos en resultados ficticios.

**Interfaces:** documento de aceptación con SHA baseline/HEAD, estado de cambios locales, matriz AC, comandos exactos/resultados, scopes/schema5, integridad, memoria y riesgos pendientes. Si no hay commit autorizado, identificar HEAD más diff pendiente; no inventar un SHA aceptado para trabajo sin commit.

- [x] Documentar arquitectura final, alineación estricta, LFE, coste de diagnósticos mono más programa, cancelación, outcomes y migración schema 4→5; actualizar próximos hitos sin declarar M6 aceptado por el usuario.
- [x] Revisar diff completo: ningún cambio de algoritmos/umbrales ni archivos fuente/producción, ningún master productivo, ninguna dependencia nueva. Comprobar enlaces locales, `git diff --check` y `git status --short`.
- [x] Entregar resultados reales con AC pendientes/fallidos explícitos. Equivalencia automatizada no sustituye validación profesional: material real y medidor externo/DAW siguen pendientes de autorización y verificación del operador si no están disponibles.
- [x] Detenerse tras informe M6. No avanzar M7, integrar rama, crear commit/tag, push ni modificar CI remotamente sin autorización propia.

## Criterio de cierre y decisiones solicitadas

**Ejecución local:** completada con las pruebas y ajustes documentados en
[M6_VALIDATION](../../M6_VALIDATION.md). La casilla de validación manual/plataformas
permanece pendiente; Linux, CI y comparación profesional no se han ejecutado.
La baseline numérica se contrastó contra una extracción temporal del commit M5,
sin cambiar ramas ni regenerar goldens. No hay commit M6 ni aceptación de release.

El trabajo puede declararse implementado cuando las tareas funcionales y regresiones locales pasan; la aceptación completa exige evidencia de todos los AC, plataformas requeridas y validación profesional acordada. Cualquier evidencia ausente se registra pendiente; un blocker produce NO-GO, nunca un PASS supuesto.

Se solicita aprobar este plan y, explícitamente, la rama local `codex/m6-programme-measurement`. Se recomienda ejecución directa en esta sesión por la dependencia estrecha entre procesos, política y reporting; alternativa disponible: ejecución por subagentes con revisión por tarea. No se ha elegido ni iniciado delegación. Ninguna modalidad autoriza publicación.
