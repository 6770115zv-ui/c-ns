---
name: android-legacy-compatibility
description: התאמת אפליקציות Android למכשירים וגרסאות ישנות, בדגש על API 19 ומעלה.
---
# Android legacy compatibility

## תהליך
1. בדוק minSdk, targetSdk, compileSdk, Gradle plugin, Java version וגרסאות AndroidX/support libraries.
2. בנה מטריצת תאימות לפי API של המכשיר בפועל. אל תניח ש־API חדש קיים רק כי compileSdk חדש.
3. לפני שימוש ב־API חדש, בדוק זמינות לפי Build.VERSION.SDK_INT והוסף fallback.
4. בדוק תמיכת ספריות ב־minSdk; אל תעלה גרסאות dependency באופן עיוור.
5. שים לב ל־storage permissions, notification APIs, background execution, TLS providers ו־WebView לפי גרסת Android.
6. במכשירים ישנים, בדוק memory pressure, multidex, method count, native ABI ו־APK signing.
7. אמת התקנה והרצה על emulator או מכשיר אמיתי באותה גרסה כשאפשר.

## כללים
- אל תסתמך על API reference של הגרסה העדכנית בלבד.
- שמור על backward compatibility בממשקי XML וב־Java APIs.
- הבדל בין הצלחת compile לבין הצלחה בזמן ריצה במכשיר היעד.
