---
name: estudio-uned
description: "Método de estudio con los materiales del campus UNED descargados por el MCP uned (~/UNED). Usar cuando el usuario quiera estudiar, resumir, repasar, hacer tests, planificar o preparar trabajos/PEC de sus asignaturas de la UNED, o pregunte por fechas, profesores o evaluación de una asignatura."
---

# Estudio UNED

El MCP `uned` mantiene una copia del campus virtual en `~/UNED`:

```
~/UNED/
  README.md               índice de asignaturas y próximas fechas
  plan-semanal.md         plan generado por uned_plan
  calendario.ics          fechas para importar en el calendario
  novedades.md            cambios de la última sincronización
  <Asignatura>/
    ficha.md              profesorado, contacto, evaluación, fechas, temario+progreso, materiales
    guia-docente.md/.pdf  guía oficial
    materiales/           archivos del aula, por sección
    texto/                texto extraído (markdown con marcas "## [p. N]")
    apuntes/              resúmenes/tests guardados
    progreso.json         estado de cada tema
```

## Procedimiento

1. **Contexto:** `uned_ficha <asignatura>` para saber qué se evalúa, cómo y cuándo. Si falta o está desactualizado, `uned_sincronizar`.
2. **Buscar antes de responder:** `uned_buscar` (búsqueda de texto completo en todos los materiales, sin acentos) y `uned_leer archivo desde_pagina hasta_pagina`.
3. **Citar** siempre *(archivo, p. N)*. Distinguir lo que dicen los materiales de conocimiento general.
4. **Producir y guardar:** resúmenes, esquemas, tests → `uned_guardar_apunte`.
5. **Progreso:** `uned_progreso_marcar` (pendiente → leyendo → visto → repasado → dominado). El planificador (`uned_plan`) usa ese estado y los ECTS para repartir horas.
6. **Trabajos evaluables:** ayudar a entender, estructurar y revisar; no redactar la entrega.

## Técnicas recomendadas

- **Recuperación activa:** tras leer un tema, preguntas sin mirar (`/uned-test`).
- **Repaso espaciado:** repasar temas `visto` a los ~2 días, `repasado` a la semana, `dominado` antes de la evaluación.
- **Elaboración:** conectar cada concepto con casos actuales y con otras asignaturas de la titulación.
- **Planificación inversa** desde la fecha de entrega para trabajos largos.

## Limitaciones

- Los PDF escaneados sin capa de texto aparecen como "pendiente OCR" en el informe de sincronización; no se pueden buscar hasta instalar `ocrmypdf` + `tesseract-ocr-spa` y volver a sincronizar con `forzar=True`.
- Vídeos y audios no se descargan (enlace en la ficha).
- Las fechas "aproximadas según la guía" no son oficiales; las del aula virtual sí.
