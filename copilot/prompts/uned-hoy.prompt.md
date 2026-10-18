---
agent: "uned-tutor"
description: "Qué tengo pendiente en la UNED y qué estudio hoy. Uso: /uned-hoy [horas disponibles]"
argument-hint: "[horas disponibles hoy]"
tools: ['uned/*']
---

# Hoy en la UNED

1. Llama a `uned_novedades` (si devuelve que nunca se ha sincronizado o la última sincronización tiene más de 2 días, llama antes a `uned_sincronizar`).
2. Llama a `uned_entregas`, `uned_clases` y `uned_progreso`.
3. Responde con:
   - **🔥 Urgente (≤7 días):** tabla fecha · asignatura · actividad · estado.
   - **📣 Novedades:** materiales o anuncios nuevos, solo lo accionable.
   - **📚 Hoy toca:** con las horas indicadas (${input:horas:2} h si no se dicen), propone 1–3 bloques concretos (asignatura, tema, material a leer con páginas aproximadas, y objetivo de la sesión), priorizando entregas cercanas y temas con más peso pendientes.
4. Termina preguntando si quiere empezar ya con el primer bloque.
