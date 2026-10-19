# M6 — diseño para revisión

Fecha: 19 de octubre de 2026. Estado: **diseño aprobado por el usuario**;
el plan de implementación requiere aprobación propia. No acredita implementación
ni pruebas ejecutadas.

## Objetivo y baseline

Medir stereo y 5.1 multiple-mono como un programa multicanal mediante FFmpeg,
sin crear un master interleaved de duración completa. El PCM y los resultados
deben concordar con una referencia interleaved construida solo para pruebas.

Baseline funcional: `d339b70026a1941ee732a5eb7962581aab0ad6c7`, tag `m5-accepted`.
La revisión documental parte de `68970dee0cee2d213bfc2e4c16e9b8e218771b8c`;
sus diferencias respecto de M5 son únicamente documentales. No se ha creado una
rama M6. Su creación, commits y publicación requieren autorización específica.

Requisitos: especificación M6 aportada por el usuario (AC01–AC18). Contratos
vigentes: [PROJECT_STATE](../PROJECT_STATE.md), [Programme Groups](PROGRAMME_GROUPS.md)
y [AGENTS](../../AGENTS.md).

Decisiones ya confirmadas por el usuario:

- Sin BWF, la medición M6 exige `common_file_start` seleccionado explícitamente;
  la inferencia automática de M5 no es suficiente.
- Incluir el control mínimo **Cancelar QC** en la GUI y cancelación controlada
  de CLI/FFmpeg. La GUI actual no dispone de cancelación.

## Enfoque recomendado y alternativas

**Extensión del backend existente:** entrada virtual con `join`, seguida por el
mismo filtro EBU R128, parser, política y gestión de procesos. Es la opción propuesta:
mantiene una sola interpretación de mediciones y exige cambios locales de integración.

Un interleaver Python hacia una tubería también podría evitar un master, pero
duplicaría decodificación, multiplexación y control de presión de las tuberías.
No se recomienda. Un motor de loudness nuevo o renderizar un master completo
quedan excluidos por alcance, mantenimiento e integridad.

## Componentes y flujo

1. Descubrir archivos y definiciones como en M5; conservar sus validaciones.
2. Inspeccionar cada archivo mediante la infraestructura actual y conservar sus
   mediciones, eventos, metadata y evidencias. Los miembros declarados tienen un
   contexto de evaluación de niveles distinto, sin modificar el preset global.
3. Construir grupos e issues M5 sin alterar predicados, tolerancias o caps.
4. Un componente nuevo `programme_measurement.py` verifica elegibilidad M6 sobre
   hechos medidos y devuelve motivos estructurados, sin aplicar umbrales QC.
5. Para cada grupo elegible y con medición solicitada, ejecutar una única pasada
   multicanal virtual; devolver mediciones y outcomes sin clasificar cumplimiento.
6. La capa de política evalúa esos resultados mediante `evaluate_level_policy`.
7. CLI/GUI e informes presentan niveles del programa, diagnóstico físico,
   cobertura de defectos y ejecución como conceptos separados.

La pasada EBU mono existente se conserva inicialmente cuando está habilitada,
como diagnóstico y para mantener los datos forenses de M5. La pasada de programa
es adicional y necesaria para gating/ponderación simultáneos: no puede derivarse
de valores mono. Este coste se declarará y se medirá; no se decodifica otra vez
para agrupar eventos ni se añade concurrencia. Omitir diagnósticos mono sería una
optimización posterior, no una refactorización implícita de este milestone.

## Elegibilidad M6

Requiere grupo M5 VALID, identidad/membresía sin ambigüedad, todos los roles
presentes una vez, fuentes distintas mono PCM WAV compatibles, sample rate y
sample counts positivos e idénticos, decode completo y ausencia de errores de
contenedor, cambios de fuente o muestras no finitas.

- Referencias BWF presentes en todos los miembros: deben ser válidas e iguales.
- BWF ausente total o parcialmente: solo admitir `requested_alignment` explícito
  `common_file_start`, con advertencia y provenance de qué referencias faltan.
  El grupo debe seguir cumpliendo la validación M5.
- Dos referencias BWF presentes y distintas rechazan M6 incluso con
  `common_file_start`; una afirmación manual no anula esa contradicción.
- BWF inválido no equivale a BWF ausente. Nada de offsets inferidos o rollover.
- M5 puede seguir agrupando un conjunto que M6 rechace: ambos estados se conservan.
- Caps de defectos no bloquean una medición completa de niveles; su aviso persiste.

Se comprueba la identidad de las fuentes (size, mtime_ns, inode cuando proceda)
entre inspección y pasada virtual y al terminar. Un cambio invalida la certificación
de las medidas afectadas. No se afirma protección frente a modificaciones externas
que eludan estas firmas; los fixtures de aceptación incorporan SHA-256 adicional.

## Construcción del stream y medidas

| Layout lógico | Posiciones FFmpeg, en orden |
| --- | --- |
| stereo | L→FL, R→FR |
| 5.1 | L→FL, R→FR, C→FC, LFE→LFE, Ls→SL, Rs→SR |

5.1 utilizará explícitamente el layout FFmpeg `5.1(side)`. La referencia de prueba
tendrá esa misma asignación; no se sustituirá por BL/BR. Cada entrada se asigna por
rol y canal físico 0 en el grafo, independientemente del orden del manifest.

Grafo propuesto: entradas mono → `join` con mapa explícito →
`ebur128=metadata=1:peak=true:dualmono=false` → `ametadata=mode=print` → salida null.
El comando usa listas de argumentos, protocolos locales y rutas como argumentos
de entrada, nunca interpoladas dentro del grafo. No usa shell, amix, ganancia,
downmix, resampling de frecuencia, trimming, padding ni delays. Las conversiones
de representación necesarias para el backend no deben alterar valores PCM; se
demostrará esa propiedad sobre fixtures, incluyendo formatos mixtos admitidos.

Reutilizar `LoudnessParser` y factorizar solo la ejecución común indispensable.
La ruta física mantiene sus parámetros y comparaciones de referencia. Verificar
también que la pasada virtual procesa el número esperado de muestras, sin confiar
exclusivamente en una duración redondeada o en que `join` acabe correctamente.

Integrated, LRA, True Peak y máximos M/S conservan los outcomes existentes.
El backend debe excluir LFE de loudness e incluirlo en True Peak; las pruebas
aisladas demostrarán ambas propiedades. Ningún cálculo promedia LUFS mono.
Silencio/bajo gate: null/UNAVAILABLE, nunca cero artificial ni PASS de un requisito
sin resultado. NaN o resultados obligatorios ausentes: ERROR y QC INCOMPLETE.
LRA sigue siendo report-only: no existen límites LRA configurables en la política.

## Política, scopes y estados

La pertenencia declarada a un programa cambia el scope de los checks de niveles,
no las medidas físicas ni sus defectos. Integración mediante contexto explícito en
la política; no eliminar mensajes por coincidencias de texto en reporting.

- Archivos ajenos a grupos: comportamiento actual, incluida su política de niveles.
- Miembros identificados de grupos: niveles mono diagnósticos; no aplicar el target
  de programa a cada mono, tampoco como fallback si el grupo no puede medirse.
- Grupo inválido/ambiguo: conservar inspección física y diagnósticos de membresía,
  con niveles del programa NOT_EVALUATED y razón explícita; nunca asignar PASS.
  Si un archivo figura en definiciones conflictivas, no elegir un propietario
  arbitrario: señalar esa ambigüedad y mantener sus mediciones físicas.
- Grupo elegible medido: un Check por requisito mediante la política común, sin
  replicar seis fallos LUFS. Clipping, dropouts y otros hallazgos técnicos persisten.
- Los errores EBU mono diagnósticos se registran como tales; no deben invalidar una
  medición de programa independiente correcta. Errores de lectura/muestras o
  integridad de fuente siguen bloqueando elegibilidad. La ruta sin grupos conserva
  íntegro el contrato de mediciones obligatorias del hotfix.
- Medición de programa solicitada pero imposible/fallida: evaluación incompleta,
  diagnóstico obligatorio, salida CLI 2. Incumplimiento acústico medido: salida 1.
  Programa silencioso: política existente de unavailable/WARNING, sin falso PASS.
- Si loudness está desactivado y no hay máximo TP, no programar la pasada EBU:
  estado DISABLED, no un error operativo. Grupo y evidencia siguen disponibles.

Cada grupo distinguirá elegibilidad, estado de ejecución de medida, outcomes por
métrica, checks de niveles y cobertura de defectos. El resultado global incluirá
checks técnicos de archivos y checks de niveles del programa, sin sumar file/group
issues como defectos únicos. Un PASS de niveles no certifica cobertura de defectos.

## Resultados, informes y compatibilidad

Usar un resultado estructurado por grupo, con método `virtual_multichannel`, mapa
de roles/fuentes, sample rate/count, alineación, firma de entradas, backend/parámetros,
mediciones, outcomes, motivos, checks y configuración de política aplicada.
Referenciar la identidad/membresía del grupo existente; no duplicar listas completas
ni modificar los AudioFile de medición como efecto lateral de reporting.

**Propuesta: JSON schema 5**, porque cambia el scope de cumplimiento de miembros
agrupados y del resultado global. Conservar campos forenses, nombres de métricas,
listas de archivos/issues y columnas CSV existentes; añadir campos de scope y
resultado de programa, sin reinterpretar silenciosamente schema 4. Los informes
históricos no se reescriben. Los valores físicos de una inspección independiente
deben permanecer idénticos; la migración de schema se documenta expresamente.

HTML y GUI: resumen por programa con layout, I/LRA/TP, estado, motivos y diagnóstico
de fuentes desplegable. Mantener visibles errores, medidas omitidas y cobertura
INCOMPLETE. CLI normal/quiet: resumen; verbose: mapa explícito y progreso.
No añadir editor de grupos ni rediseñar la GUI. No sintetizar evidencia multicanal
de multiple-mono: conservar enlaces de M5 y su provenance.

## Cancelación y ciclo de procesos

Añadir «Cancelar QC», habilitado solo durante el escaneo. La GUI solicita
cancelación cooperativa al CLI mediante su canal local de control; propuesta:
stdin de QProcess con un modo interno de control, sin sockets ni archivos de audio.
FFmpeg conserva stdin desconectado del operador.

Una señal/token de cancelación del CLI se consulta entre fases y durante los
subprocesos. El gestor común termina y espera su FFmpeg; tras un plazo acotado
de gracia, lo mata y recoge. Debe funcionar también si stdout no produce datos.
Ctrl+C usa la misma limpieza. No matar solo el CLI dejando su hijo huérfano.

Salir 130, mostrar Cancelado y reactivar controles cuando termine la limpieza.
No crear `QC_COMPLETE.json` ni anunciar reportes completos en un escaneo cancelado.
Si existen resultados recuperables, conservarlos claramente como parciales;
ausencia de recuperación por error de disco debe quedar diagnosticada. No borrar
evidencias existentes ni modificar fuentes. No afirmar soporte Windows sin pruebas;
validación obligatoria en macOS y Linux, plataformas ya utilizadas por el proyecto.

## Verificación y aceptación

Fixtures deterministas pequeños generados localmente; referencia interleaved y
monos derivados de los mismos enteros PCM. El render completo se permite solo
como fixture de prueba, nunca en la ruta productiva. Mantener pruebas existentes
y no regenerar goldens para aceptar desviaciones.

| Criterios | Demostración requerida |
| --- | --- |
| AC01–02 | Stereo y 5.1: PCM idéntico y comparación I/LRA/TP contra ruta física |
| AC03–04 | Manifest barajado y canales asimétricos/aislados; comprobar PCM por rol, no solo loudness, que puede ocultar permutaciones |
| AC05–06 | LFE solo: loudness no medible; TP incluye su señal; ensayo adicional con LFE como máximo y programa activo |
| AC07–10 | Miembros ausentes, sample rates/counts distintos y BWF contradictorio rechazan sin correcciones silenciosas |
| AC11–12 | Mismo evaluador y thresholds; un fallo de programa, ningún fallo LUFS duplicado por mono |
| AC13–14 | Ruta física sin regresiones numéricas; CLI/GUI coinciden con snapshot y fixture iguales |
| AC15 | Cancelación real durante pasada virtual desde GUI y CLI; comprobar terminación del PID FFmpeg, controles y marcador de informe |
| AC16 | SHA-256, size, mtime_ns, rutas/nombres y metadata antes/después; ninguna salida interleaved productiva |
| AC17 | Comparar programas sintéticos de 30 y 600 s con generación por bloques; muestrear RSS del CLI y FFmpeg, registrar picos y curva |
| AC18 | Silencio, bajo gate y LFE solo distinguidos de ejecución fallida; null y estados correctos |

AC17 debe mostrar memoria estable tras calentamiento, sin retener muestras ni
metadata por duración. Presupuesto inicial de crecimiento entre duraciones:
≤64 MiB adicionales por proceso; cualquier exceso exige investigar y justificar,
no cambiar el límite solo para aprobar. Medir RSS de los hijos además del padre;
esta prueba empírica no constituye una demostración matemática para toda duración.

Comparación numérica: buscar igualdad de la salida del mismo backend; techo de
aceptación I ≤0,1 LU, LRA ≤0,1 LU y TP ≤0,1 dB. Registrar también diferencias sin
redondeo y no tolerar un sesgo sistemático sin explicación. TP mantiene inicialmente
la resolución existente de 0,1 dB. LRA debe ejercitarse con niveles variables y
ventanas suficientes, no solo una sinusoide constante que dé LRA trivial.

Añadir fallos controlados de FFmpeg, timeout, salida malformada/incompleta, cambios
de fuente, rutas Unicode/espacios, BWF ausente/mixto y explicit common start, límites
de frames y cobertura de defectos truncada. Ejecutar focalizadas primero y suite
completa después. Ajustar expectativas solo por cambios de scope/schema aprobados,
con pruebas que conserven el comportamiento físico y de agrupación anterior.

Separar aceptación automatizada de validación profesional con material de referencia
y medidor externo/DAW. Esta última requiere material autorizado y comparación del
operador; si falta, se declara pendiente, sin certificar equivalencia profesional.

## Alcance y aprobación siguiente

Sin M7/M8, mejoras del detector, --compare, nuevas dependencias, nuevos layouts,
normalización, sincronización automática, Docker o paralelización de scans.
El diseño no autoriza commits, pushes, merges ni usar material de producción.

Tras aprobación de este documento se redactará el plan de implementación con
pasos, archivos, comandos verificables y matriz AC. Se solicitará autorización
para una rama M6 que conserve los documentos vigentes, sin modificar `main` ni el
tag M5. La ejecución requiere aprobación del plan; no se considera iniciada aquí.
