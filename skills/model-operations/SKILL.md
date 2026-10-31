---
name: model-operations
description: תפעול מודלי LLM מקומיים או בענן, GGUF, llama.cpp, GPU, quantization ו־inference.
---
# LLM model operations

## תהליך
1. אמת model repository, file pattern, quantization, license ודרישות זיכרון.
2. בדוק GPU model, VRAM, driver, CUDA runtime, compute capability ו־available system RAM.
3. אמת שהבינארי תואם ל־GPU ולספריות הריצה; בדוק ldd ו־--version.
4. בחר context, batch, GPU layers ו־parallelism לפי זיכרון פנוי ולא לפי מפרט תאורטי בלבד.
5. בדוק health endpoint לפני שליחת prompt; שמור server logs כשיש כשל.
6. אמת תשובת מודל, finish_reason, tokens/sec ושימוש בזיכרון.
7. הפרד בין model download, server startup, inference ו־tool calling בבדיקת תקלות.

## כללים
- ציין את quantization והקשר שבו נמדדו ביצועים.
- אל תסיק שכל VRAM פנוי זמין למודל אם יש תהליכים אחרים.
- אל תציג benchmark חד־פעמי כמדד יציב.
