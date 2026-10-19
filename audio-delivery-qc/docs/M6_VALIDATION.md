# M6 — registro de ejecución

Plan: `docs/superpowers/plans/2026-10-19-m6-programme-measurement.md`.
Estado: implementación local validada; publicación de la rama autorizada posteriormente;
aceptación de release pendiente. Baseline funcional d339b700;
HEAD documental inicial 68970dee. Rama autorizada `codex/m6-programme-measurement`.

## Decisiones y continuidad

- Ruling: ejecución directa y rama local sin worktree adicional, conforme al plan
  aprobado; sin commits ni publicación. El registro permanece aquí, no se utiliza
  tooling de Skill que presuponga commits o cambie exclusiones Git.
- Pre-flight: tareas 2/4/5/7 comparten token explícito opcional; cancelación deriva
  de KeyboardInterrupt para atravesar handlers genéricos sin fabricar errores.
- Pre-flight: tareas 3/4/5/6 comparten resultado estructurado, outcomes existentes y
  copia de grupos; agrupación M5 no se modifica. Scope de niveles solo en política.
- Pre-flight: tareas 1/4/8 comparten fixtures; mapa esperado independiente del
  código productivo. Referencia interleaved solo en pruebas.

## Resultados

Logs de baseline: `/tmp/xqc-m6-baseline-tests.log`.

- Baseline: 627 passed / 0 failed / 0 skipped, 26.91 s; Python 3.14.8,
  macOS ARM64, FFmpeg 9.0.2. Referencias PCM: 2 passed.
- Cancelación + hotfix/robustez/loudness: 75 passed, 6.53 s. Elegibilidad + M5: 89 passed.
- GUI focalizada y regresión Qt: 29 passed, 2.51 s.
- Ruling: FFmpeg 9 join perdió 2560 muestras finales de forma intermitente con
  bloques de decodificación variables (573440 frente a 576000). Reagrupar cada
  entrada con asetnsamples=1024:p=0, sin añadir/quitar muestras; comprobar número
  exacto y PCM. No confiar en exit 0 ni redondear duración. Coste: filtro de
  empaquetado adicional, cubierto por equivalencia por rol y memoria.
- Ruling: schema5 y scope de programa requieren actualizar aserciones schema4,
  textos M5 y salida 0/1 en el caso de grupos inválidos con medición solicitada.
  Goldens, cálculos, tolerancias y aserciones de evidencia se conservan. Añadir
  levels_required como input operativo distingue error mono opcional de obligatorio.
- Primera suite de integración: 654 passed, 15 failed, 30.41 s. Fallos limitados
  a expectativas anteriores de schema/scope y configuración de fixture nueva
  fuera de rango; correcciones en curso. No es aceptación final.


## Evidencia local actual (19/10/2026)

- Suite posterior a integración: **684 passed, 0 failed, 0 skipped**, 35.99 s.
  Comando: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`.
  Log: `/tmp/xqc-m6-regression-final.log`. Revisión independiente aún en curso;
  si requiere correcciones, se registra aquí el resultado posterior.
- `.venv/bin/python -m pytest -q tests/test_virtual_loudness.py tests/test_programme_policy.py`:
  25 passed, 3.96 s antes de añadir la regresión de I ERROR + TP FAIL.
  Esta regresión falló inicialmente y ahora pasa; política: 7 passed.
- GUI M6 con QProcess real y snapshot: 3 passed, 0.98 s. Es automatización Qt
  offscreen, no validación manual del operador en la aplicación ni DAW.
- `.venv/bin/python -m pytest -q tests/test_virtual_reports.py`: 2 passed.
  Corrección RED→GREEN: conservar el AudioFile ya medido cuando se cancela
  exportación de evidencia; recuperación disponible sin QC_COMPLETE.
- `.venv/bin/python scripts/verify_m6.py --output /tmp/xqc-m6-acceptance-20261019-a --memory`:
  finaliza correctamente. `acceptance.json` y reportes HTML/JSON están en ese
  destino nuevo. Solo audio sintético. Se autorizó técnicamente la consulta local
  de RSS fuera del sandbox; no hubo red ni acceso a material de producción.
- `.venv/bin/python scripts/verify_hotfix_release.py --output /tmp/xqc-m6-hotfix-20261019-a`:
  finaliza correctamente con los seis escenarios operativos históricos repetidos.
  Log `/tmp/xqc-m6-hotfix.log`. No se modificó el runner del hotfix.
- Comparación con código extraído mediante `git archive d339b700...` a un directorio
  temporal (sin worktree ni cambio de referencias): **10 WAV** stereo/5.1 y miembros,
  mismos diccionarios `measurements`, `measurement_outcomes`, `defects` y `bwf`.
  Resultados `/tmp/xqc-m6-measures-baseline.json` y `/tmp/xqc-m6-measures-current.json`;
  ambos registran ruta de import para demostrar las implementaciones comparadas.
- Gramática Python 3.11 comprobada con `ast.parse(feature_version=(3,11))` en 75
  archivos; **no equivale a ejecución con Python 3.11**.

### Escenarios operativos M6 (todos sintéticos)

| Caso | Medición programa | Audio QC | Ejecución | Exit |
| --- | --- | --- | --- | --- |
| A conforme | SUCCESS | PASS | COMPLETED | 0 |
| B TP no conforme | SUCCESS | FAIL | COMPLETED | 1 |
| C FFmpeg fallido, inyección controlada | ERROR | INCOMPLETE | PARTIAL | 2 |
| D exportación evidencia fallida | SUCCESS, medidas conservadas | PASS | PARTIAL | 2 |
| E silencio | SUCCESS; I null/UNAVAILABLE | WARNING | COMPLETED | 0 |
| F informe HTML fallido (ENOSPC simulado) | SUCCESS | PASS conservado en recovery | FAILED | 2 |

F no genera QC_COMPLETE. D no inventa defecto acústico por fallo de escritura.
La prueba adicional I ERROR + TP FAIL conserva ambos hechos y la ejecución
incompleta; una métrica fallida no borra incumplimientos válidos de otra.

### Matriz de aceptación

| AC | Evidencia local | Estado |
| --- | --- | --- |
| 01–02 stereo/5.1 | test_virtual_metrics_and_pcm; runner: delta I/LRA/TP = 0,0 en ambos layouts | PASS local |
| 03–04 mapa y permutación | PCM por rol independiente, manifest/entradas invertidas; formatos PCM mixtos | PASS local |
| 05–06 LFE | LFE solo: I UNAVAILABLE, TP −0,4 dBTP; caso LFE dominante con programa activo | PASS local |
| 07–10 elegibilidad | test_programme_measurement, regresiones programme; samples/rate/BWF exactos y referencia >2**53 | PASS local |
| 11–12 política | test_programme_policy/test_virtual_cli; una evaluación de niveles del programa; mono diagnóstico | PASS local |
| 13 físico | goldens existentes intactos + comparación exacta 10 WAV contra M5 | PASS local |
| 14 GUI/CLI | QProcess real, valores/snapshot/summary, CLI e informes | PASS automatizado macOS; manual pendiente |
| 15 cancelar | hijo bloqueado, pasada virtual FFmpeg real, GUI/control local, exit130 y recovery | PASS local; Linux pendiente |
| 16 integridad | SHA-256/size/mtime todos los fixtures del runner; no master en ruta productiva | PASS local |
| 17 memoria | 30 frente a 600 s, seis mono, curva RSS padre/hijo | PASS local |
| 18 silencio | null/outcomes independientes; LFE solo/bajo gate distintos de fallo | PASS local |

Memoria (KiB): CLI 39920 → 39808; mayor hijo 39344 → 41888. Crecimiento
−112 / +2544 KiB, dentro de 65536 KiB por proceso. Las curvas completas constan
en acceptance.json; es evidencia empírica para esos fixtures, no prueba universal.
Los interleaved completos son exclusivamente referencias sintéticas de prueba.

## Límites de aceptación y Git

- M5 continúa siendo la baseline aceptada/tag `m5-accepted`. M6 es trabajo local
  sin commit: HEAD sigue siendo `68970dee0cee2d213bfc2e4c16e9b8e218771b8c` más diff.
- No ejecutados: Linux, runtime Python 3.11, CI remota, Windows, material real,
  medidor externo/DAW y validación profesional. No se afirma equivalencia certificada.
- No se han autorizado publicaciones, nuevas dependencias ni servicios externos.
  Los archivos temporales de evidencia pueden expirar; el runner reproduce los casos.
- M6 no se declara aceptado por el usuario. **NO-GO para aceptación/release completa**
  mientras falten Linux/CI y validación profesional acordada; implementar M7/M8
  no está autorizado. La revisión independiente y sus correcciones se documentan a continuación.


## Cierre de revisión independiente

Un revisor independiente, de solo lectura, encontró tres problemas importantes;
no hubo hallazgos críticos ni menores diferidos. No se realizó una segunda revisión:
se verificaron las correcciones mediante regresiones RED→GREEN y suite completa.

1. Recuperación tras cancelación: ahora conserva el informe ya construido o los
   grupos completados, sus medidas/provenance y configuración. Grupos pendientes
   son NOT_EVALUATED; análisis parcial es INCOMPLETE, sin falso PASS físico.
2. Cancelación simultánea con excepción: el token prevalece en la salida excepcional
   del proceso y del CLI. Se recoge el hijo, devuelve 130 y se conserva el error
   concurrente en diagnósticos de recuperación cuando hay datos disponibles.
3. Fallo de lectura BWF: bloquea elegibilidad igual que cualquier diagnóstico que
   invalide el análisis de fuente. Ya no se confunde con ausencia legítima de BEXT.

Las cinco variantes iniciales reprodujeron los problemas (5 failed, 5.58 s).
Tras corrección: **51 passed, 8.51 s** en selección de elegibilidad, cancelación,
reportes, GUI, backend virtual y CLI. Una regresión adicional comprueba cancelación
entre dos programas: conserva el primero SUCCESS y marca el segundo NOT_EVALUATED.

AC15 se verificó además de extremo a extremo: GUI/QProcess → CLI → FFmpeg virtual
real (ralentizado solo en el fixture), petición del botón durante progreso EBU,
exit130, PID de FFmpeg terminado y ausencia de QC_COMPLETE. La limitación pendiente
es Linux y validación manual del operador, no la unión automatizada GUI/backend.

**Resultado definitivo de suite:**
`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` →
**690 passed, 0 failed, 0 skipped, 38.56 s**.
Log `/tmp/xqc-m6-regression-reviewed.log`.

Hotfix repetido después de correcciones:
`python scripts/verify_hotfix_release.py --output /tmp/xqc-m6-hotfix-20261019-reviewed`
→ escenarios A–F aprobados (B incluye loudness y TP separados), integridad verdadera.
No se cambia el significado histórico de ningún resultado anterior.

Ruling de cierre: conservar rama y diff sin commit/publicación, conforme al alcance
aprobado; no se ofrece ni ejecuta integración automática desde la Skill de cierre.
Los riesgos de portabilidad y equivalencia profesional siguen pendientes de
verificación, no se sustituyen por la suite macOS ni por gramática Python 3.11.

## Componentes entregados

- `programme_measurement.py`: elegibilidad, mapa explícito, stream virtual, firmas
  y resultados; `loudness.py`: backend/parser compartido y conteo exacto.
- `rules.py`, `measurement.py`, `scanner.py`, `cli.py`: scope, scheduling y estados.
- `process.py`, fases de lectura y `gui_window.py`: cancelación y limpieza.
- `reports/`: schema5, niveles del programa, diagnóstico físico y recuperación.
- Nuevas pruebas M6 y `scripts/verify_m6.py`; cambios a tests anteriores limitados
  a schema/scope y nuevo input operativo. Goldens existentes intactos.
- README, Programme Groups, PROJECT_STATE, diseño y plan: continuidad y límites.

No se modificaron `defects.py`, `consolidation.py`, `issues.py`, `programme.py`,
`timecode.py`, BWF, presets, dependencias ni workflows CI. Las fuentes de audio
no se incorporan a Git. Comprobados enlaces relativos, estado Git y diff --check.


Aceptación operacional M6 repetida sobre el código corregido:
`python scripts/verify_m6.py --output /tmp/xqc-m6-acceptance-20261019-reviewed`.
Resultados en `acceptance.json`; reporte 5.1:
`/tmp/xqc-m6-acceptance-20261019-reviewed/report-surround/QC_REPORT.html`.
La memoria ya se midió en el destino `...-a --memory`; las correcciones posteriores
no cambian el grafo virtual ni retención de muestras. No se repitió esa medición.
