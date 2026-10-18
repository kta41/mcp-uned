---
agent: "uned-tutor"
description: "Resumen y esquema de un tema UNED a partir de los materiales descargados, con citas de página. Uso: /uned-resumen <asignatura> <tema>"
argument-hint: "<asignatura> <tema o material>"
tools: ['uned/*']
---

# Resumen de tema

Petición: **${input:tema}**

1. Identifica la asignatura y el tema. Usa `uned_materiales` para ver qué archivos corresponden al tema y `uned_buscar` con los conceptos del título del tema.
2. Lee el material con `uned_leer` por bloques de páginas hasta cubrirlo (no te quedes con el primer fragmento).
3. Escribe el resumen con esta estructura:
   - **Idea central** (3–4 líneas).
   - **Esquema** jerárquico del tema.
   - **Conceptos clave**: término — definición breve *(archivo, p. N)*.
   - **Autores, teorías, fechas y documentos** relevantes.
   - **Conexiones** con otros temas de la asignatura o de la titulación.
   - **Lo que más probablemente se evalúa**, según la guía docente (`uned_ficha`).
   - **3 preguntas de autocomprobación** (sin respuesta; se responden en `/uned-test`).
4. Guárdalo con `uned_guardar_apunte` (título: "Resumen — <tema>").
5. Propón marcar el tema como `visto` con `uned_progreso_marcar`.
