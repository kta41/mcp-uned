---
agent: "uned-tutor"
description: "Ficha completa de una asignatura UNED (profesorado, contacto, evaluación, fechas, temario, materiales). Uso: /uned-ficha <asignatura>"
argument-hint: "<asignatura>"
tools: ['uned/*']
---

# Ficha de asignatura

Asignatura: **${input:asignatura}**

1. Llama a `uned_ficha` con esa asignatura (si no existe la ficha, llama antes a `uned_sincronizar` para esa asignatura).
2. Presenta un resumen de una pantalla:
   - Profesorado y cómo contactar (correo, teléfono, horario de atención).
   - Cómo se evalúa: pruebas, ponderación y requisitos (nota mínima, número de páginas, penalizaciones…).
   - Próximas entregas y fechas (diferenciando fechas del aula virtual y aproximadas de la guía).
   - Temario con estado de progreso.
   - Materiales clave por tema (los que más peso o páginas tienen).
3. Señala riesgos o requisitos fáciles de pasar por alto (p. ej. "mínimo 40 encuestados", "no se acepta fuera de plazo").
4. Indica la ruta del archivo `ficha.md` completo.
