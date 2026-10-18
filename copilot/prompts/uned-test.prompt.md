---
agent: "uned-tutor"
description: "Test de repaso interactivo sobre un tema o asignatura UNED, corregido con citas y que actualiza tu progreso. Uso: /uned-test <asignatura> [tema]"
argument-hint: "<asignatura> [tema] [nº preguntas]"
tools: ['uned/*']
---

# Test de repaso

Petición: **${input:tema}**

1. Determina la asignatura y el tema (si no hay tema, elige los temas en estado `visto` o `repasado` de `uned_progreso`, priorizando los de más peso y los menos repasados).
2. Recupera el contenido con `uned_buscar` y `uned_leer`. Las preguntas deben salir **solo** de los materiales.
3. Haz 10 preguntas (o las que pida el alumno), **de una en una**, esperando su respuesta: ~60% tipo test con 4 opciones, ~40% respuesta corta/desarrollo breve, al estilo de la evaluación descrita en la guía.
4. Tras cada respuesta: correcto/incorrecto, explicación breve y cita *(archivo, p. N)*.
5. Al final: nota sobre 10, conceptos fallados y qué releer.
6. Actualiza el progreso con `uned_progreso_marcar`: ≥8 → `dominado`; 6–8 → `repasado`; <6 → `visto` con nota de qué falló.
7. Guarda las preguntas falladas con `uned_guardar_apunte` (título: "Errores test — <tema>") para repasarlas más tarde.
