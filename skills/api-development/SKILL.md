---
name: api-development
description: תכנון ומימוש API ושרתי backend, חוזי JSON, אימות קלט, הרשאות וטיפול בשגיאות.
---
# API and backend development

## תהליך
1. בדוק את ה־API הקיים, routes, schemas, authentication וגרסאות לקוחות.
2. הגדר חוזה ברור: method, path, headers, request, response, status codes ושגיאות.
3. אמת קלט בצד השרת; אל תסמוך על ולידציה בדפדפן.
4. הפרד authentication מ־authorization ובדוק הרשאות לכל resource.
5. השתמש ב־timeouts, pagination, rate limits ו־idempotency היכן שנדרש.
6. תעד דוגמאות בקשה/תגובה והוסף בדיקות success/error.
7. בדוק backward compatibility לפני שינוי API קיים.

## כללים
- אל תדליף stack traces, secrets או פרטי תשתית לתגובה ציבורית.
- אל תתעלם מ־HTTP status codes ואל תחזיר 200 על כשל.
- שמור על schema עקבי ואל תשנה שמות שדות בלי מעבר מתוכנן.
