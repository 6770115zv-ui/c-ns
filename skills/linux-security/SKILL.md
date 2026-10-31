---
name: linux-security
description: ביקורת אבטחה הגנתית לקוד Linux/Android, הרשאות, תהליכים, sandbox והקשחת תצורה.
---
# Defensive Linux security review

בצע ביקורת הגנתית רק על קוד, מערכת או סביבה שהמשתמש מורשה לבדוק.

## תחומים לבדיקה
- גבולות אמון, privilege transitions, capabilities, uid/gid ו־file permissions.
- input validation, path traversal, symlink races, command injection ו־unsafe deserialization.
- חשיפת secrets דרך environment, logs, artifacts, process arguments ו־Git history.
- sandbox escape surface, network egress, metadata services, mounts ו־shared directories.
- dependency versions, supply chain, workflow permissions ו־untrusted pull request execution.

## תהליך
1. בנה threat model: נכסים, תוקפים אפשריים, גבולות אמון והשפעה.
2. אתר נקודות קלט ופעולות privileged.
3. לכל ממצא תן קובץ/שורה, תרחיש, השפעה, חומרה והמלצת תיקון.
4. הוסף regression test שמוכיח שהממצא תוקן.
5. בדוק שההקשחה לא שוברת שימוש תקין.

## כללים
- אל תטען שאין פרצות; ציין scope ומה לא נבדק.
- אל תבצע פעולות על מערכות צד שלישי ללא הרשאה.
- העדף תיקונים, הקשחה ובדיקות בטוחות על פני ניצול בפועל.
