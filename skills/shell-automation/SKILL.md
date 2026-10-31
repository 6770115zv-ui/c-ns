---
name: shell-automation
description: כתיבת Bash scripts אוטומטיים, בטוחים, idempotent וקלים לאבחון.
---
# Shell automation

## תהליך
1. קבע shell target וגרסאות זמינות.
2. השתמש ב־quoting לכל משתנה שמכיל path או קלט; העדף arrays על בניית command string.
3. בחר set -euo pipefail כשמתאים, אבל טפל במפורש בפקודות שמותר להן להיכשל.
4. הפוך פעולות setup ל־idempotent כדי שניתן יהיה להריץ מחדש.
5. בדוק exit codes, timeouts, signals ו־cleanup של תהליכי רקע.
6. כתוב לוגים שמסבירים שלבים בלי לחשוף סודות.
7. בדוק path עם spaces, קלט ריק ותיקיות שאינן קיימות.

## כללים
- הימנע מ־eval ומ־curl | bash כשאפשר.
- השתמש ב־mktemp לקבצים זמניים והגדר trap לניקוי.
- אל תשתמש ב־sudo רחב אם אפשר לתת הרשאה לפעולה נקודתית.
