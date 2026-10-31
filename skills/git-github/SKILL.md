---
name: git-github
description: עבודה בטוחה עם Git ו־GitHub: branches, commits, diffs, Actions, Issues ו־PRs.
---
# Git and GitHub

## תהליך
1. בדוק branch, HEAD, working tree, remotes והיסטוריית commits לפני שינוי.
2. קרא את הקבצים הרלוונטיים ואת הוראות CONTRIBUTING/README.
3. בחר שינוי ממוקד; שמור על שינויים קיימים של המשתמש.
4. בדוק git diff --check, tests וסטטוס לפני commit.
5. כתוב commit message תיאורי. אל תדחוף secrets, build outputs או קבצים זמניים.
6. לאחר push, אמת את ה־commit ב־remote ואת מצב ה־workflow שמופעל.
7. ב־PR, תאר סיכון, בדיקות ותוכנית rollback.

## GitHub Actions
- הבדל בין queued, in_progress, completed ו־conclusion.
- בדוק job steps ולוגים; heartbeat או workflow dispatch אינם הוכחת הצלחה.
- בדוק artifacts ותוצרי build כשאלה רלוונטיים.

## כללים
- אל תבצע force-push או מחיקה רחבה בלי בקשה מפורשת.
- לעולם אל תדווח commit/push שלא התקבל על ידי GitHub.
