---
name: android-development
description: פיתוח Android ב־Java/Kotlin, תאימות API, Gradle, ADB, הרשאות וממשקי משתמש.
---
# Android development

## תהליך
1. קרא AndroidManifest.xml, קובצי Gradle, minSdk, targetSdk, compileSdk, מבנה Java/Kotlin ומשאבים.
2. בדוק את גרסת Android והחומרה בפועל. אל תניח ש־API מודרני זמין במכשיר ישן.
3. בחר API לפי minSdk; עטוף קריאות חדשות בבדיקות גרסה והוסף fallback כשצריך.
4. שמור על threading נכון: פעולות I/O ופקודות ארוכות אינן רצות ב־UI thread.
5. בדוק lifecycle, הרשאות runtime, storage model, exported components ו־PendingIntent flags לפי גרסת Android.
6. בנה APK ובדוק לפחות compile. כשהמכשיר מחובר, התקן והריץ ואסוף logcat.
7. דווח בנפרד על build מוצלח, התקנה מוצלחת והרצה פונקציונלית — אלה שלבים שונים.

## תאימות לאחור
- לפני שימוש ב־AndroidX או API חדש, בדוק אם הגרסה תומכת ב־minSdk של הפרויקט.
- במכשירים ישנים, בדוק תמיכה ב־Java language desugaring, תכונות framework וגרסאות dependency.
- אל תסיר תמיכה בגרסאות ישנות בלי אישור מפורש.
