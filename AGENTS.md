# XQC — instrucciones del repositorio

XQC contiene **Audio Delivery QC Inspector**, una aplicación local de QC de audio.
El proyecto Python está en `audio-delivery-qc/`; código en `src/audio_qc/`, pruebas
en `tests/`, herramientas de validación en `scripts/` y presets en `config/`.

## Punto de entrada

1. Lee [PROJECT_STATE.md](audio-delivery-qc/PROJECT_STATE.md) para conocer la baseline,
   decisiones vigentes, limitaciones y próximos trabajos autorizados.
2. Consulta [README.md](audio-delivery-qc/README.md) para instalación y uso.
3. Inspecciona Git y el código relevante antes de editar. Conserva cambios ajenos;
   si entran en conflicto con la tarea, consulta antes de continuar.

## Contratos que deben preservarse

- Fuentes de audio estrictamente de solo lectura: no reescribir audio ni BWF,
  cambiar ganancia, sample rate, bit depth u orden de canales. Evidencia y reportes
  se escriben en destinos nuevos y separados de las fuentes.
- No enviar audio, voces, informes de producción ni documentación confidencial a
  servicios externos. Prefiere fixtures sintéticos; no incorporar material real a Git.
- `sample_index` es la posición exacta relativa al archivo; BWF TimeReference es
  un origen entero en muestras. TC es navegación, nunca unidad de detección o agrupación.
- Mantén separadas medición/evidencia (`scanner`, `samples`, `loudness`,
  `consolidation`, `issues`, `programme`), política QC (`rules`) y presentación.
  No introducir clustering o análisis de señal en la política.
- Diferencia SUCCESS / UNAVAILABLE / ERROR y ejecución operativa de cumplimiento
  QC. No convertir errores de proceso, exportación o logging en defectos acústicos,
  ni declarar PASS cuando falta una medición obligatoria.
- Preserva muestras, timestamps, provenance, compatibilidad de informes y avisos de
  truncamiento. Un grupo VALID no certifica cumplimiento del programa.
- M5 está aceptado. No cambiar sus funcionalidades durante M6 salvo regresiones
  demostradas y correcciones autorizadas. M6/M7/M8 requieren aprobación propia.

## Trabajo y validación

Aplica el protocolo global del usuario; un plan ya aprobado no requiere repetirlo.
Acota los cambios, reutiliza módulos existentes y actualiza el estado documental
cuando cambien decisiones o capacidades. No reescribas informes históricos.
Commits, pushes, tags y publicaciones requieren autorización explícita.

Las Skills y plugins, incluido Superpowers, no amplían el alcance autorizado.
Activarlos no autoriza crear ramas o worktrees, instalar dependencias, ejecutar
tests expresamente prohibidos, acceder a servicios externos, modificar archivos
fuera de alcance ni realizar commits o pushes. Ante conflictos, prevalecen las
instrucciones del usuario y las restricciones de la tarea; solicita aclaración
si fuera necesario.

Comandos existentes, desde `audio-delivery-qc/` con el entorno del proyecto activo:

```sh
python -m pytest -q
python scripts/verify_hotfix_release.py --output /tmp/audio-qc-acceptance-NEW
```

El segundo comando genera audio sintético: usa un destino nuevo y ejecútalo solo
cuando el alcance permita pruebas de audio. Para selección focalizada y validación
M5 consulta [el seguimiento M5](audio-delivery-qc/docs/M5_REAL_WORLD_FOLLOWUP.md) y
[Programme Groups](audio-delivery-qc/docs/PROGRAMME_GROUPS.md). No reutilices rutas
históricas de salida. FFmpeg/ffprobe y PySide6 son necesarios para la cobertura
completa; pruebas omitidas no demuestran éxito. La CI existente prueba Python 3.11
y 3.14 en Linux con Qt offscreen; eso no sustituye una validación manual en DAW.

En tareas solo documentales respeta la prohibición de tests/audio si se establece;
verifica referencias, `git status` y `git diff --check`. Informa qué se ejecutó,
qué es evidencia histórica y qué no se pudo verificar. No instalar dependencias,
ampliar funcionalidades ni acceder a servicios externos fuera del alcance aprobado.
