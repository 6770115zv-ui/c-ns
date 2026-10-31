---
name: performance-optimization
description: מדידת ביצועים, profiling, איתור צווארי בקבוק, זיכרון, latency וצריכת משאבים.
---
# Performance optimization

## תהליך
1. הגדר מדד: latency, throughput, memory, CPU, GPU, I/O או startup time.
2. מדוד baseline בסביבה מייצגת ותעד פקודה, נתונים וגרסה.
3. השתמש ב־profiler או metrics כדי למצוא את צוואר הבקבוק בפועל.
4. שנה גורם אחד בכל פעם והשווה לאותו baseline.
5. בדוק tradeoffs: זיכרון מול מהירות, caching מול freshness, parallelism מול contention.
6. בצע בדיקת עומס או benchmark חוזר, כולל מספר ריצות וטווח פיזור.
7. ודא שלא נפגעה נכונות התוצאה.

## כללים
- אל תבצע אופטימיזציה על סמך תחושת בטן.
- ציין חומרה, גודל קלט, concurrency וגרסאות.
- אל תציג שיפור זעיר כמשמעותי בלי נתונים.
