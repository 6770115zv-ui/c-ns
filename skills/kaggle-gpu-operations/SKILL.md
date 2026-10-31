---
name: kaggle-gpu-operations
description: תפעול Kaggle kernels ו־GPU דרך GitHub Actions, כולל T4, מגבלות סשן, artifacts ו־logs.
---
# Kaggle and GPU operations

## תהליך
1. בדוק kernel metadata: owner/slug, language, GPU, internet, privacy ו־input sources.
2. אמת שה־Kaggle username, API token ו־kernel reference תואמים.
3. הפרד בין push של kernel, queue/start, model download, server startup ו־inference.
4. בדוק nvidia-smi, GPU count, VRAM per GPU, driver/CUDA versions, RAM ושטח דיסק.
5. בדוק האם המודל וה־quantization מתאימים לזיכרון בפועל; חשב גם context/KV cache.
6. בדוק status דרך Kaggle CLI והצלב עם GitHub Actions logs ו־artifacts.
7. בסיום, ודא שהפלט נשמר וש־processes/worker נסגרים כדי לא לבזבז quota.

## תקלות נפוצות
- 409: Kernel קודם עדיין רץ או שה־slug תפוס.
- no matching GGUF: תבנית הקובץ אינה תואמת לקבצים בריפו המודל.
- server not healthy: בדוק binary, CUDA libraries, VRAM, logs ו־health endpoint.
- context allocation failure: הקטן context או parallelism ובדוק KV cache.

## כללים
- אל תכריז שהמודל רץ לפי הצלחת push בלבד.
- ציין מספר GPUs בפועל ולא מספר שהוגדר בקובץ.
- הפרד בין Kaggle kernel runtime לבין GitHub Actions runner.
