# Previsualización de Programme Groups sin bloquear la GUI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. No crear ramas, worktrees, commits ni pushes sin autorización específica.

**Estado:** implementado y validado localmente el 26/10/2026. Publicación autorizada
posteriormente el mismo día; la validación local no certifica CI remota.

**Goal:** mantener la interfaz disponible durante el descubrimiento de grupos y mostrar únicamente resultados correspondientes a la selección vigente.

**Architecture:** proceso auxiliar local gestionado por QProcess, independiente del proceso QC existente. Reutiliza `scanner.discover` y `programme.discover_programmes`; recibe una copia de fuente/configuración y devuelve una previsualización informativa. La GUI aplica resultados por identificador de solicitud, sin utilizarlos como entrada autoritativa del QC.

**Tech Stack:** Python y PySide6 ya instalados; JSON por stdin/stdout, sin dependencias nuevas.

**Spec:** alcance propuesto en esta conversación: descubrimiento en segundo plano, estado visible, cancelación/descarte de resultados obsoletos y equivalencia de agrupación. Contratos generales en [AGENTS.md](../../../../AGENTS.md); estado del producto en [PROJECT_STATE.md](../../../PROJECT_STATE.md).

## Evidencia inspeccionada

- Base: `f1ba7233fbf9d711a806691ad063080cc41fe607`, rama `codex/m6-programme-measurement`.
- `gui_window.py:200`: `update_group_preview` ejecuta `exists`, `discover` y `discover_programmes` en el hilo de interfaz.
- `gui_window.py:322`: `scan_arguments` ya conserva un snapshot independiente de la configuración; debe mantenerse.
- `gui_window.py:403`: `scan_finished` escribe el resumen final en el mismo panel; una búsqueda anterior nunca debe sobrescribirlo.
- `tests/test_programme_gui.py` comprueba mapping, snapshot y escaneo real, pero presupone previsualización síncrona.
- Git contiene únicamente `graphify-out/` sin seguimiento antes de preparar este documento. No se ha reproducido el bloqueo ni ejecutado tests en esta fase.

## Decisión y alternativas

Se propone QProcess porque el proyecto ya lo utiliza y permite terminar un trabajador de solo lectura sin forzar la destrucción de un hilo Python. QThread sería una alternativa más ligera, pero una llamada de filesystem bloqueada no responde necesariamente a cancelación cooperativa y complica el cierre seguro. No se modifica el proceso QC existente.

## Restricciones

- Fuentes estrictamente de solo lectura, sin decode ni análisis acústico en la previsualización.
- Mismas extensiones, orden, symlinks y reglas de grupos que el descubrimiento canónico.
- No alterar detectores, umbrales, política QC, formatos de informe, M5/M6 ni configuración efectiva del escaneo.
- Sin red, dependencias nuevas, material de producción o cambios en `graphify-out/`.
- Un trabajador activo y como máximo una solicitud pendiente: la más reciente. No cola creciente al editar la ruta.
- La previsualización no certifica existencia, alineación ni cumplimiento: la validación de medios sigue ocurriendo durante QC.

## Casos críticos de revisión

1. Cambios rápidos A → B → C: solo C puede actualizar el panel.
2. Inicio/fin del QC mientras existe una búsqueda: el resultado tardío no toca el estado ni el resumen del QC.
3. Cerrar, desactivar grupos o cambiar YAML durante la búsqueda: cancelar sin esperas bloqueantes en el hilo GUI.
4. Carpetas inaccesibles/desaparecidas y fallo del auxiliar: diagnóstico visible, nunca confundir fallo con «no hay grupos».
5. Árboles y nombres grandes/Unicode: salida limitada, sin inundar el event loop ni interpretar texto como HTML.

## Tarea 1 — Auxiliar de descubrimiento y contrato de resultados

**Archivos:** crear `src/audio_qc/group_preview.py` y `tests/test_group_preview.py`.

**Interfaz propuesta:** `python -m audio_qc.group_preview`, una solicitud JSON por stdin con `request_id`, `source`, `settings` normalizados. Respuesta JSON con `request_id`, estado, texto, número total de grupos, avisos de descubrimiento y truncamiento de presentación. No crear reportes ni archivos temporales.

- [x] Escribir pruebas de equivalencia contra las funciones canónicas: stereo/5.1, YAML explícito, naming, Unicode, espacios, symlinks y ruta vacía/inexistente.
- [x] Observar el fallo antes de implementar el auxiliar.
- [x] Reutilizar las funciones existentes sin duplicar sus reglas; mover también la comprobación inicial de la ruta a este proceso.
- [x] Limitar stdout/stderr recibidos y texto mostrado (presupuesto propuesto: 256 KiB por canal). Mostrar aviso si el resumen se abrevia; nunca truncar los inputs del QC por este límite visual.
- [x] Probar errores de permisos, respuesta inválida y salida excesiva con fixtures controlados. La lista canónica de descubrimiento mantiene su coste actual; no prometer memoria constante para árboles arbitrarios.

## Tarea 2 — Integración asíncrona y ciclo de vida

**Archivos:** modificar `src/audio_qc/gui_window.py`; crear `src/audio_qc/group_preview_gui.py` y `tests/test_group_preview_gui.py`; adaptar `tests/test_programme_gui.py` y el teardown de ventanas en `tests/conftest.py` al cierre asíncrono.

- [x] Añadir pruebas que demuestren que un timer/evento GUI sigue ejecutándose con el auxiliar detenido mediante una barrera de prueba, sin depender de sleeps para ordenar resultados.
- [x] Añadir estado de solicitud vigente y snapshot profundo de fuente/settings. Invalidarlo inmediatamente al editar la fuente; agrupar cambios rápidos mediante un timer corto antes de lanzar la nueva búsqueda.
- [x] Mostrar «Buscando archivos…» y actualizar widgets solo desde señales recibidas en el hilo GUI.
- [x] Cancelar el auxiliar anterior con terminate y, si no termina, kill tras un plazo breve. No usar waitForFinished ni terminar el proceso QC por error.
- [x] Cubrir A → B → C, cambio/desactivación de grupos, cierre y errores; verificar que no sobreviven procesos auxiliares en los escenarios probados.
- [x] Al iniciar QC, invalidar/cancelar la previsualización. Run QC no dependerá de su resultado; conservará su snapshot y validación canónica actuales.
- [x] Probar que ningún callback tardío sobrescribe el resumen final del QC ni su configuración, progreso o botones.

## Tarea 3 — Regresión y documentación

- [x] Ejecutar tests nuevos y regresión GUI/configuración/descubrimiento/grupos, incluidos los escaneos sintéticos existentes.
- [x] Ejecutar `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` completo desde `audio-delivery-qc/`.
- [x] Comprobar integridad de fixtures sintéticos en las pruebas que ejecuten QC; comparar mapping y configuración efectiva con la ruta canónica.
- [x] Hacer smoke GUI si el entorno lo permite; separar explícitamente Qt offscreen de validación manual con discos reales.
- [x] Actualizar README y PROJECT_STATE con comportamiento, pruebas y límites; revisar diff y `git diff --check`.

## Aceptación y limitaciones

Aceptación: interfaz operativa mientras se descubre, solo resultados vigentes, agrupación equivalente, cancelación/cierre sin esperas síncronas, errores explícitos, regresión completa sin fallos y sin cambios acústicos.

No se garantiza cancelación instantánea de una llamada de sistema bloqueada por el sistema operativo. Los diálogos nativos, la carga del YAML y otras comprobaciones de rutas fuera de la previsualización no quedan convertidos automáticamente a trabajo asíncrono. No se rediseña la GUI ni se acepta una release/M7 con esta tarea.

**Publicación:** no incluida en esta propuesta; requerirá autorización expresa cuando el cambio esté implementado y validado.

## Registro de ejecución

- Se conserva la rama actual y `graphify-out/`, sin worktrees ni publicaciones.
- Decisión de implementación: separar el controlador Qt en `group_preview_gui.py`
  para mantener el protocolo/ciclo de vida fuera de la ventana y permitir importar
  el auxiliar sin PySide6. Contrato compartido: IDs enteros de solicitud y JSON
  acotado; la ventana nunca usa esta respuesta como configuración del QC.
- IPC: 4 MiB por solicitud; 256 KiB retenidos por canal de salida; texto generado
  de hasta 16 Ki caracteres más un aviso/resumen breve. Rebasar la solicitud
  bloquea solo la previsualización, no el QC. Debounce de 150 ms; escalada de
  terminate a kill tras 300 ms sin esperas bloqueantes.
- TDD: 12 casos del auxiliar fallaron antes de existir el módulo; después pasaron.
  La prueba GUI inicial falló antes de implementar el proceso auxiliar. Un caso
  adicional detectó que un directorio denegado se presentaba como sin grupos;
  se corrigió el mensaje sin alterar los avisos del descubrimiento canónico.
- El primer parametrizado de entrada excesiva produjo un identificador de test
  excesivamente largo (también propagado por pytest al entorno del subprocess).
  Se sustituyó solo el identificador por `oversize`, manteniendo el payload y
  todas las aserciones de error y límites.

- Revisión final: el revisor independiente detectó que los caracteres no BMP
  ocupan 12 bytes en JSON ASCII, no 6. Dos pruebas nuevas reprodujeron el exceso
  (383.747 bytes y rechazo en GUI); se redujo el presupuesto a 16 Ki caracteres,
  incluyendo margen para el envoltorio y los avisos. La revisión delegada quedó
  interrumpida por límite de uso; se completó inspección local del diff.
- Validación final 26/10: 164 pruebas focalizadas aprobadas (12,70 s); suite completa
  828 aprobadas, 0 fallidas, 8 omitidas (55,14 s, runtime opcional Essentia).
  Python 3.14.8/macOS ARM64/FFmpeg 9.0.2. Smoke GUI offscreen y QC stereo sintético
  con SHA-256/tamaño/mtime intactos. Sin validación manual de escritorio o DAW,
  ni CI remota para este diff. Comandos completos en PROJECT_STATE.md.
