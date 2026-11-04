---
name: ai-agent-engineering
description: תכנון, מימוש והערכה של מערכות agents וכלי עבודה.
---
# AI agent engineering

## תכנון
1. הגדר מטרה, גבולות, מקורות נתונים ותנאי הצלחה.
2. הפרד בין orchestration, model inference, tools, state ו-observability.
3. תכנן כלים עם schemas ברורים, ולידציה, timeouts ופלט מוגבל.
4. השתמש ב-state machine מפורש ובמנגנון retry idempotent.
5. שמור trace של קריאות כלים, תוצאות ושגיאות בלי לרשום credentials.

## סביבת עבודה
- סביבת Linux זמינה דרך bash, וסביבת Windows דרך win_powershell כאשר ה-Windows executor מחובר.
- בדוק את סטטוס הסביבה לפני קריאת כלי; אל תניח ש-Workspace פועל רק מפני שהמודל פעיל.
- קבצי Linux נשמרים בענף workspace; קובצי Windows בענף workspace-windows.
- Skills מתארים יכולות; הם לא יוצרים הרשאות. בדוק את כלי ה-runtime בפועל.

## הרשאות
- סביבת Linux מריצה פקודות כ-root. סביבת Windows מריצה פקודות תחת חשבון Administrator של runner.
- פקודות Workspace יורשות את סביבת ה-executor, שעשויה להכיל GH_TOKEN וסודות workflow. אין להדפיס או להעביר אותם לפלטים.
- התייחס לכלי Workspace כהרצת קוד מהימן עם השפעה על כל סביבת ה-runner. סביבת GitHub-hosted זמנית, אך הרשאות token תקפות בזמן הריצה.

## איכות
- בדוק קלטים, שגיאות, timeout, מגבלות פלט ונתיבים.
- הרץ בדיקות בפועל לפני דיווח הצלחה.
- דווח אילו פקודות הורצו, מה הצליח ומה נותר לא מאומת.
