# Prompt de edición para Remotion

> **Pega aquí tu prompt de edición.**
>
> Este texto se copia automáticamente dentro de cada proyecto Remotion que
> genera la app (en `storage/outputs/{job_id}/remotion/PROMPT_EDICION.md`), para
> que lo uses como guía al editar en Remotion Studio o al pasárselo a una IA de
> código (Claude Code, Cursor, etc.) que edite la composición.
>
> La app también genera, junto a este prompt:
> - `timeline.json` → la “receta” de cada clip (fragmentos, tiempos, transiciones,
>   subtítulos y música).
> - `beats/` → los fragmentos ya normalizados a 1080x1920 que referencia el timeline.
> - una composición Remotion de ejemplo que lee ese `timeline.json`.

<!-- ───────────────  TU PROMPT EMPIEZA AQUÍ  ─────────────── -->

🎬 MEGA-PROMPT — Edición de video con Remotion (1 sola instrucción)
Copia y pega todo lo de abajo en tu code. Solo cambia los valores entre [CORCHETES] cuando hagas un video nuevo.

CONTEXTO
Actúa como editor de video senior especializado en Remotion y en contenido para redes sociales (Reels / TikTok / Shorts). Vas a editar un video completo de principio a fin en una sola pasada, sin pedirme aprobaciones intermedias salvo que algo sea técnicamente imposible.
Archivo de entrada: [C:\Users\danie\OneDrive\Escritorio\Ediciones\ANUNCIO_1.mp4] Producto / marca: [Kéfir / lacto-fermentos artesanales] Objetivo: anuncio dinámico y moderno que maximice engagement y termine en venta. CTA final: texto en pantalla que diga "Haz clic para conseguir el tuyo" (con un botón/enlace animado a WhatsApp). NO mostrar el número de WhatsApp en pantalla.

REGLAS OBLIGATORIAS (no negociables)
1. Audio
Conserva SIEMPRE el audio original del video. No lo silencies ni lo recortes.
Añade música de fondo libre de derechos a volumen bajo (que no tape la voz original; mézclala a ~15–20% del volumen, con ducking si la voz sube).
Añade SFX (whoosh, pop, ding) en las transiciones y apariciones de texto, pero con moderación: solo donde refuercen un momento, no en cada elemento.
Descarga tú mismo la música y los SFX desde fuentes libres de derechos (ej. Pixabay, Mixkit, Freesound) y déjalos en una carpeta /public/audio. Si no puedes descargar, dime exactamente qué archivo falta y dónde colocarlo.
Debe teener por lo menos 2 animaciones breves a pantalla completa.
2. Sincronización con la voz (CRÍTICO)
Las animaciones de texto deben coincidir con lo que se dice en el audio. Ejemplo: la animación de la palabra "Kéfir" debe aparecer en el segundo exacto en que la voz dice "kéfir", no antes ni después.
Antes de animar, transcribe el audio con marcas de tiempo (timestamps) y usa esos tiempos para disparar cada animación y cada subtítulo. La voz y los gráficos deben ir en sincronía, no por caminos separados.
3. Subtítulos
Añade subtítulos llamativos sincronizados palabra por palabra (o frase corta por frase corta) con el audio.
Estilo legible: fuente gruesa, alto contraste, contorno o sombra, animación sutil de aparición. Que se lean sin sonido.
4. Encuadre y seguridad de texto (CRÍTICO — esto fallaba antes)
Ningún título, texto o gráfico puede salirse del cuadro. Respeta un margen seguro (safe area) de mínimo 8–10% en cada borde.
Antes de dar por listo, revisa cada título y verifica que cabe completo dentro del frame (incluido el texto que crece o se anima). Ajusta tamaño de fuente automáticamente (auto-fit / word-wrap) para que nunca se desborde.
Formato vertical para redes (1080×1920) salvo que el video original sea horizontal; respeta la relación de aspecto del archivo de entrada.
5. Estilo visual: limpio, NO sobrecargado
Tono dinámico y moderno, pero simple y elegante. Animaciones bonitas, no saturadas.
NO incluyas: cinta/banda amarilla, barra de progreso superior, ni elementos decorativos que recarguen la pantalla.
Menos elementos, mejor ejecutados. Cada animación debe tener un propósito.
6. Momento de pantalla completa
En una parte clave del video (por ejemplo al presentar el producto o un beneficio fuerte), incluye una animación a pantalla completa (full-screen) que rompa el ritmo y capte atención. Solo una, bien colocada, para que tenga impacto.
7. Cierre / CTA
Termina con la animación del CTA: "Haz clic para conseguir el tuyo" + botón/enlace animado hacia WhatsApp.
Sin número visible. El botón es el call-to-action.

ENTREGABLE
Genera todo el proyecto Remotion funcional (composición, componentes, assets de audio).
Estructura el código de forma ordenada y comenta los puntos donde se sincroniza con el audio.
Cuando esté listo para previsualizar, avísame con el comando exacto para correr el preview (ej. npx remotion preview) y dime la duración final del video.
Si algo no se pudo descargar o resolver automáticamente, dame una lista corta y concreta de lo que falta.

CHECKLIST FINAL (revísalo antes de decir "listo")
Audio original intacto
Música de fondo + SFX integrados y mezclados sin tapar la voz
Animaciones sincronizadas con timestamps reales del audio
Subtítulos legibles y sincronizados
Ningún texto/gráfico se sale del cuadro (safe area respetada)
Sin cinta amarilla ni barra de progreso ni elementos recargados
Una animación full-screen bien ubicada
CTA "Haz clic para conseguir el tuyo" sin número de WhatsApp



<!-- ───────────────  TU PROMPT TERMINA AQUÍ  ─────────────── -->
