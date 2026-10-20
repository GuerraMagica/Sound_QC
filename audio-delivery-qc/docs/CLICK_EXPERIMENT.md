# Experimento local de clicks — plan y registro

Plan aprobado en conversación: comparar baseline `2e74a097455dbb30cd2f2df312e078aeae35a426`
(sensibilidad low), contexto temporal y predicción lineal sobre Print Masters.
No cambiar la aplicación. Objetivo reservado: 50 % menos falsas alarmas y retener
90 % de los clicks reales detectados por baseline. Audio real local, sin publicaciones.
El usuario pidió preparar herramienta y plantilla; etiquetará material real después.

## Registro de implementación

- Base: `2e74a09`, rama existente, árbol inicialmente limpio.
- Tareas: (1) manifiesto/métricas; (2) scoring y lectura acotada; (3) ejecución,
  congelación e informes; (4) validación sintética, revisión y regresión.
- Interfaces compartidas: intervalos half-open absolutos en muestras, canales
  físicos one-based, programme y split explícitos. El matching usa representantes
  originales, no posiciones estimadas por los scorers.
- Ruling: conservar rama actual y registrar aquí decisiones duraderas; no ejecutar
  scripts de Skills que creen worktrees, commits o cambien exclusiones Git. El
  plan aprobado prohíbe esas acciones y no requiere un archivo de plan adicional.
- Ruling: evaluar eventos por canal; mostrar issues originales aparte. No sumar
  ambos como defectos únicos. Las reducciones se calculan sin alterar agrupación.
- Ruling: límite de 60 s por fragmento, 200 fragmentos, 2.000 anotaciones por
  fragmento y 128 MiB de PCM temporal por fragmento. Permite lecturas por bloques
  y evita cargar masters completos o listas ilimitadas en memoria.

## Uso y anotación

Herramienta independiente; no añade opciones a la GUI ni modifica el detector,
la política QC, los dropouts o los presets de producción. No requiere entrenamiento
ni dependencias nuevas. Usar el entorno existente con FFmpeg/ffprobe.

1. Copiar [la plantilla](examples/click_experiment.yaml) a una carpeta local externa
   al repositorio. Ajustar rutas (relativas al YAML), sample rate, canales e intervalos.
2. Escuchar y etiquetar clicks técnicos confirmados como `technical_click`, pasos,
   armas y demás transitorios intencionados como `intentional_transient`; dudas como
   `uncertain`. No basta con etiquetar solamente los candidatos del detector: anotar
   también clicks que este omita. `reviewed: true` declara revisión completa del intervalo.
3. Separar programas completos entre development y validation, nunca fragmentos del
   mismo programa entre ambos. Reservar al menos dos programas independientes. No
   reutilizar la reserva para ajustar umbrales después de consultar sus resultados.
4. Ejecutar, desde `audio-delivery-qc`, con un destino nuevo separado de las fuentes:

```sh
.venv/bin/python scripts/evaluate_clicks.py --manifest /ruta/experimento.yaml --output /ruta/resultados-nuevos
```

Fuentes mono, stereo o seis canales PCM. Para 5.1 seleccionar `[1, 2, 3, 4, 5, 6]`;
los números identifican canales físicos, no una asignación automática de altavoces.
Las muestras son enteras relativas al archivo; extremo final exclusivo. BWF y TC
no se usan para decidir si un candidato coincide con una anotación. Tolerancia de
matching: 1 ms inclusivo, en muestras, mismo archivo/fragmento y canal.

## Comparación reproducible

Baseline fija identificada por SHA y hashes de módulos importados, sensibilidad
`low`. Se conserva su agrupación y el representante original. Se evalúan ventanas
25/50 ms y umbrales 4/8/16/32 para contexto temporal y predicción lineal bidireccional.
La predicción usa orden proporcional al sample rate (24 a 48 kHz, límites 4–64).
Estos parámetros son hipótesis experimentales, no una calibración profesional.
Contexto insuficiente, silencio no ajustable o predicción inestable conservan el
candidato. Un confirmador no recupera clicks omitidos por la baseline.

Selección exclusivamente en development, priorizando menos falsas alarmas con
retención emparejada de al menos 90 % de los clicks detectados por baseline. Desempate:
contexto temporal, ventana menor, umbral menor. `frozen_selection.json` se escribe
antes de analizar validation y se comprueba su hash al terminar. También se compara
la mejor variante de cada método, sin seleccionar de nuevo con la reserva.

`VIABLE` exige en reserva real: ≥20 clicks detectados por baseline, ≥20 falsas
alarmas, ≥2 programas, reducción ≥50 % y retención ≥90 %. Datos sintéticos no cuentan
para esta puerta. Candidatos sin etiqueta, truncamiento, análisis incompleto,
evidencia fallida o fuentes alteradas impiden aceptar. Las dudas se contabilizan
por separado y se excluyen de las métricas confirmadas. No prueban ausencia de error.
El matching es uno a uno; detecciones duplicadas de un click cuentan como falsas
alarmas adicionales. No se pueden compensar clicks perdidos con otros distintos.

## Salidas y límites

- `report.html`, `results.json`, `candidates.csv`: resultados globales/por programa,
  candidatos retenidos/descartados y provenance; JSON por fragmento con datos originales.
- Evidencia WAV para todos los candidatos descartados, agrupada por issue original,
  conservando canales, orden y amplitud mediante el exportador existente. Enlaces locales.
- `manifest_snapshot.json`, selección congelada, hashes de código, versiones y huellas
  SHA-256/tamaño/mtime antes/después. `EXPERIMENT_COMPLETE.json` solo tras entregar informes.
  Ante fallo, `EXPERIMENT_ERROR.json` cuando el disco lo permita; nunca significa QC PASS.
- Salida CLI: 0 VIABLE, 1 NOT_VIABLE, 2 error operativo, 3 INSUFFICIENT_EVIDENCE,
  130 cancelación. Un resultado insuficiente es normal con la plantilla o datos sintéticos.

Recuentos por evento de canal físico, separados de los issues originales. Tasas por
hora de fuente y hora de canal, no supuesto número único de defectos de un programa.
Los JSON conservan clicks omitidos por cada método. Tiempo y memoria trazada de
Python/NumPy se registran; **no** incluyen RSS de FFmpeg ni buffers del SO.

Procesamiento por bloques y spool temporal ≤128 MiB por fragmento; ≤60 segundos,
≤200 fragmentos, ≤2000 anotaciones por fragmento, YAML ≤2 MiB. El límite compartido
original de 1000 issues permanece y bloquea aceptación si se alcanza. Los límites
no garantizan duración corta: FFmpeg decodifica desde el principio para recortar
muestras exactas; elegir archivos cortos facilita la evaluación. El contexto se
lee alrededor del fragmento; no equivale a inspeccionar el master completo.

Solo rutas locales; nada se sube. Salidas con audio real deben estar fuera del
repositorio. No incluir fuentes, snippets ni informes reales en Git. Se rechazan
solapamientos y copias idénticas entre programas, pero no se puede reconocer por
hash audio reutilizado tras cambiar metadata/encoding: la independencia del corpus
requiere revisión humana. Un resultado VIABLE tampoco demuestra reconocimiento
semántico de intención artística ni autoriza integrar el método en producción.

## Validación de implementación — 20/10/2026

Revisión independiente de solo lectura: se corrigieron dos riesgos de falsa mejora.
El matching que encuentra clases distintas dentro de tolerancia queda `unclassified`
y bloquea aceptación; una variante no puede reasignarlo de falsa alarma a click.
Las copias byte-idénticas se verifican también por canal e intervalo, incluso dentro
del mismo programa. Ambas correcciones tienen pruebas que fallaron antes del arreglo.
También se corrigió la cobertura de contexto a 8 kHz, alineándola a los bloques
reales del detector; reproducción fallida seguida de prueba satisfactoria.

Prueba CLI ejecutada con tres WAV sintéticos stereo PCM24/BWF de tres segundos,
un programa de desarrollo y dos de reserva. Baseline reservada: 2 clicks etiquetados
y 2 transitorios intencionados detectados; selección congelada temporal/25 ms/16.
Salida real: `INSUFFICIENT_EVIDENCE`, exit 3; fuentes SHA-256/tamaño/mtime intactas.
Tiempo observado 0,418 s; pico trazado 4.662.011 bytes (no RSS total). Se generaron
HTML/JSON/CSV y evidencia de descartados. Estos números validan el recorrido técnico,
no eficacia perceptiva: los transitorios de esta prueba son impulsos sintéticos.

Pruebas focalizadas: `python -m pytest -q tests/test_click_experiment.py`: **27 passed**.
Incluyen seis canales con evidencia sin cambio de orden/amplitud, fallo de escritura,
no finitos, rango inválido, fuga de corpus, separación previa de reserva, posiciones
exactas y límites de matching. No se ha realizado escucha en DAW ni evaluación real.

Regresión completa ejecutada en macOS/ARM64, Python 3.14.8, FFmpeg 9.0.2:
`python -m pytest -q`: **717 passed in 40.78s**, sin fallos ni omisiones.
Plantilla validada (3 fragmentos, todos pendientes de revisión); enlaces HTML locales
comprobados con destino existente y atributos `target="_blank" rel="noopener"`.
Código de producción sin modificaciones. No se ejecutó CI remota ni se publicó.

Registro cerrado: tareas 1–4 implementadas y verificadas con fixtures sintéticos;
evaluación real pendiente. Decisiones de alcance: rama conservada y sin commits;
métricas por canal (no defectos únicos); límites de fragmento explícitos (material
más largo exige dividir intervalos sin solapar). No quedan observaciones menores
diferidas de la revisión independiente.
