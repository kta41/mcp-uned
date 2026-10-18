---
agent: "uned-tutor"
description: "Plan de estudio semanal para las asignaturas UNED según créditos, entregas y progreso. Uso: /uned-plan [horas/semana] [semanas]"
argument-hint: "[horas por semana] [semanas]"
tools: ['uned/*']
---

# Plan de estudio

Petición: **${input:horas}**

1. Si el alumno no dice horas por semana, asume 10 h y 4 semanas y dilo.
2. Llama a `uned_entregas`, `uned_clases`, `uned_progreso` y `uned_plan` con esas horas y semanas.
3. Presenta el plan semana a semana (tabla: asignatura · horas · qué temas/actividades · entregable), explicando en 2–3 líneas el criterio (entregas cercanas, créditos, temas pendientes).
4. Señala conflictos: semanas con varias entregas, trabajos largos que hay que empezar ya, exámenes.
5. Ofrece exportar las fechas con `uned_calendario_ics` para importarlas en Outlook/Google Calendar.
