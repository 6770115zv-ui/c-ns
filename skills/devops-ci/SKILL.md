---
name: devops-ci
description: בניית pipelines של GitHub Actions, deployment, artifacts, caching, secrets ו־runner orchestration.
---
# DevOps and CI/CD

## תהליך
1. מפה triggers, jobs, dependencies, permissions, concurrency ו־timeouts.
2. תן לכל job את ההרשאות המינימליות הדרושות בלבד.
3. הפרד build, test, package ו־deploy; השתמש ב־artifacts להעברת תוצרים.
4. שמור secrets ב־GitHub Secrets או OIDC; אל תדפיס אותם ואל תעביר אותם ל־untrusted jobs.
5. הגדר cache לפי lockfiles וגרסאות, לא לפי הנחות.
6. טיפול בכשל חייב לכלול log ברור, exit code תקין ו־cleanup.
7. אחרי deployment אמת health ותרחיש שימוש אמיתי, לא רק הצלחת dispatch.

## כללים
- pin versions/actions לפי מדיניות הפרויקט.
- הימנע מ־pull_request_target כאשר מריצים קוד לא מהימן.
- בדוק concurrency groups כדי למנוע ריצות כפולות או race על משאב משותף.
