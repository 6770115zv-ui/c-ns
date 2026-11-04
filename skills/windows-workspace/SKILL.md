---
name: windows-workspace
description: שימוש בסביבת Windows Workspace ב-GitHub Actions עם PowerShell והרשאות Administrator.
---
# Windows Workspace

## מתי להשתמש
השתמש בסביבת Windows כאשר המשימה דורשת Windows APIs, PowerShell, MSBuild, Visual Studio Build Tools, .NET, winget, Chocolatey, התקנות MSI/EXE, בדיקות Windows או יצירת קובצי EXE.

## כלים זמינים
- win_get_environment: בדיקת מערכת ההפעלה, המשתמש, מצב Administrator וגרסאות כלים.
- win_powershell: הרצת PowerShell בתוך תיקיית סביבת העבודה. אפשר להעביר timeout בשניות (ברירת מחדל 120, מקסימום 600).

## הרשאות וסביבה
- סביבת העבודה מופעלת על GitHub-hosted windows-latest.
- ה-Workflow בודק שה-process token חבר בקבוצת Windows Administrators.
- פקודות PowerShell רצות באותו חשבון מוגבה ומקבלות את משתני הסביבה של ה-executor, כולל GH_TOKEN. לכן יש להניח שלפקודות יש הרשאות ניהול וגישה לסודות וליכולות הכתיבה של ה-Workflow.
- זהו runner זמני. התקנות מערכתיות וקבצים מחוץ לתיקיית Workspace נעלמים בסיום ה-runner; רק קובצי Workspace נשמרים בענף workspace-windows.
- אין להדפיס, להעתיק או להעלות ערכי סודות ללוגים, ל-Issues או לענף Workspace.

## תהליך עבודה
1. בדוק חיבור והרשאות עם win_get_environment.
2. השתמש ב-Get-Location, Get-ChildItem -Force ובפקודות PowerShell רגילות כדי להבין את סביבת העבודה.
3. כתוב קבצים לתיקייה הנוכחית או לתת-תיקיות שלה; היא מסונכרנת אוטומטית לענף workspace-windows.
4. להתקנות, בדוק תחילה מה זמין: Get-Command winget,choco,dotnet,msbuild -ErrorAction SilentlyContinue.
5. השתמש ב-winget, choco, pip, npm, dotnet או מתקינים רשמיים לפי הצורך. אם התקנה דורשת reboot או GUI, הסבר את המגבלה.
6. בדוק exit code ופלט. עבור פרויקט, הרץ build/test אמיתיים לפני דיווח הצלחה.
7. שמור תוצרים וקובצי פרויקט בתוך Workspace, ולא בתיקיות זמניות מחוץ לו.

## PowerShell
- העדף -LiteralPath עבור נתיבים, ו-ErrorAction Stop כאשר כשל צריך לעצור את הסקריפט.
- השתמש ב-$LASTEXITCODE לאחר תוכניות native כגון git, npm או dotnet.
- צטט נתיבים עם רווחים.
- פקודות PowerShell יכולות לשנות את כל סביבת ה-runner; בצע שינויים מכוונים בלבד.
