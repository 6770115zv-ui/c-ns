---
name: database-sql
description: תכנון סכמות SQL, שאילתות, אינדקסים, טרנזקציות, migrations וגיבויים.
---
# Database and SQL

## תהליך
1. בדוק את מנוע בסיס הנתונים, גרסה, schema, migrations וקצב/גודל נתונים.
2. תכנן constraints ו־types כך שימנעו נתונים לא תקינים.
3. השתמש ב־parameterized queries; לעולם אל תשרשר קלט משתמש לשאילתה.
4. נתח query plan לפני הוספת אינדקסים או שינויי ביצועים.
5. שמור על transactions ועל atomicity של פעולות מרובות שלבים.
6. כתוב migrations שניתנות לשחזור וחשוב על rollback.
7. בדוק השפעה על נתונים קיימים ועל גרסאות תוכנה קודמות.

## כללים
- אל תריץ migration הרסנית ללא גיבוי ותוכנית שחזור.
- אל תציג נתוני משתמש רגישים בלוגים.
- בדוק concurrency, locks ו־isolation במקומות רגישים.
