---
name: shell-automation
description: כתיבת Bash ו-PowerShell scripts אוטומטיים, idempotent וקלים לאבחון.
---
# Shell automation

## בחירת shell
1. בדוק את מערכת ההפעלה ואת הכלים הזמינים.
2. Linux: השתמש ב-Bash. Windows Workspace: השתמש ב-PowerShell דרך win_powershell.
3. אל תניח שפקודות Bash זמינות ב-Windows או שפקודות PowerShell זמינות ב-Linux.

## תהליך
1. קבע shell target וגרסאות זמינות.
2. השתמש ב-quoting לכל משתנה שמכיל path או קלט; העדף arrays על בניית command string.
3. הפוך פעולות setup ל-idempotent כדי שניתן יהיה להריץ מחדש.
4. בדוק exit codes, timeouts, signals ו-cleanup של תהליכי רקע.
5. כתוב לוגים שמסבירים שלבים בלי לחשוף סודות.
6. בדוק paths עם spaces, קלט ריק ותיקיות שאינן קיימות.

## Bash
- השתמש ב-set -euo pipefail כשמתאים, אבל טפל במפורש בפקודות שמותר להן להיכשל.
- השתמש ב-mktemp וב-trap לניקוי קבצים זמניים.
- הימנע מ-eval ומ-curl | bash כשאפשר.

## PowerShell
- העדף -LiteralPath עבור נתיבים.
- השתמש ב--ErrorAction Stop כאשר כשל צריך לעצור את הסקריפט.
- בדוק $LASTEXITCODE אחרי תוכניות native.
- צטט נתיבים עם רווחים.
