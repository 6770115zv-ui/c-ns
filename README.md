# cpu-and-gpu-ai-runs

מודל שפה (Qwen3.6-35B-A3B) שרץ על GPU חינמי של Kaggle, כשהכול מופעל ומנוהל מ-GitHub:
- **Run on Kaggle** – משימה אחת, תשובה ב-Summary, קבצי קוד שחולצו עם קישור הורדה.
- **צ'אט** – דף ב-GitHub Pages. ההודעות נשמרות כתגובות ב-Issues, וworker ב-Kaggle עונה להן.
- **סביבת עבודה** – runner של GitHub Actions שמריץ בשביל המודל פקודות bash / Python / Java וכו', ושומר את הקבצים בענף `workspace`.

## התקנה חד-פעמית

1. **Secrets בריפו** (Settings → Secrets and variables → Actions):
   - `KAGGLE_USERNAME` – שם המשתמש (handle) ב-Kaggle, כפי שהוא מופיע ב-`kaggle.com/code/<שם>/...`
   - `KAGGLE_API_TOKEN` – אסימון (kaggle.com/settings/api → Generate New Token)
2. ב-Kaggle: אימות טלפון בחשבון (בלי זה אין GPU).
3. Actions → **Build llama.cpp (CUDA, T4)** → Run workflow (פעם אחת, כ-25 דקות).
4. **GitHub Pages:** Settings → Pages → Source: *Deploy from a branch* → Branch: `main`, תיקייה `/docs`.
   הדף יהיה ב-`https://<משתמש>.github.io/<ריפו>/`.
5. **טוקן לדף הצ'אט:** github.com/settings/personal-access-tokens/new
   - Repository access: *Only select repositories* ← הריפו הזה בלבד
   - Permissions: **Issues: Read and write**, **Actions: Read and write**, Metadata: Read
   - הדביק אותו בהגדרות הדף (⚙️). הוא נשמר רק ב-localStorage של הדפדפן.

## שימוש

### משימה בודדת
Actions → **Run on Kaggle** → כתוב prompt (והגדל `max_tokens` לדף HTML מלא, 8000 ומעלה).
בסוף ב-Summary: התשובה, וקישור **הורדת קבצי הקוד** (הקישור דורש התחברות ל-GitHub).

### צ'אט
1. פתח את דף ה-Pages ולחץ **הפעל Worker** (או Actions → **Start chat worker**). לוקח כ-4-6 דקות.
2. כשהסימן הופך ל"Worker מחובר", כתוב הודעה. התשובה מגיעה כתגובה ב-Issue.
3. ה-worker נסגר לבד אחרי 30 דקות בלי הודעות (ניתן לשנות), או אחרי כ-5 שעות. אפשר גם ללחוץ **עצור Worker**.
4. הודעה שנשלחה כשה-worker כבוי תיענה כשיופעל.
5. `/think` בתחילת הודעה מפעיל מצב חשיבה.

אפשר גם לכתוב ישירות תגובה ב-Issue עם התווית `chat` (למשל מאפליקציית GitHub בטלפון).

### סביבת עבודה (vibe coding)
1. בדף לחץ **הפעל סביבה** (או Actions → **Start workspace (executor)**). לוקח כדקה.
2. כשגם "סביבה מחובר", המודל מקבל שלושה כלים: `bash`, `write_file`, `read_file`, ומריץ אותם בלולאה (עד 15 צעדים להודעה): כותב קבצים, מריץ, רואה שגיאות ומתקן.
3. כל כלי שהמודל מריץ מופיע בצ'אט ככרטיס (פקודה ופלט), כך שאפשר לעקוב בזמן אמת.
4. הקבצים נשמרים ב-`/home/sandbox/work` ונדחפים לענף **`workspace`** בריפו כל כ-2 דקות, ובסיום. הכפתור **📁 קבצים** בדף מציג אותם (עם תצוגה מקדימה ל-HTML). בהפעלה הבאה הקבצים משוחזרים מהענף.
5. נסגר לבד אחרי 45 דקות בלי פעילות, או בכפתור **עצור סביבה**.

הערות: ב-runner של GitHub מותקנים Python 3, Java (JDK 8/11/17/21), Node.js, gcc ו-git, ויש גישה לאינטרנט (pip / npm / maven עובדים). הגבלות: עד 6 שעות להפעלה, 4 ליבות ו-16GB.


## Skills ויכולות

המודל מקבל חבילות Skills מודולריות מתוך `skills/*/SKILL.md`. בזמן Push ל-Kaggle, הסקריפט אורז את החבילות לתוך ה-Kernel הפרטי. ה-worker יכול לקרוא ל-`list_skills` כדי לראות את הקטלוג ול-`read_skill` כדי לטעון רק את ההוראות הרלוונטיות למשימה.

חבילות ה-Skills המובנות כרגע (20 חבילות):
- **פיתוח ותיקון:** software-engineering, debugging, testing-quality, technical-writing.
- **תשתיות וכלים:** devops-ci, shell-automation, git-github, model-operations, kaggle-gpu-operations.
- **פיתוח אפליקציות:** android-development, android-legacy-compatibility, frontend-web, ux-accessibility, api-development.
- **ניתוח ומחקר:** web-research, python-data, database-sql, performance-optimization.
- **Agents ואבטחה:** ai-agent-engineering, linux-security.

כלי סביבת העבודה הורחבו וכוללים:
- `bash`, `write_file`, `read_file`.
- `list_files` למיפוי תיקיות.
- `search_files` לחיפוש טקסט בקבצים.
- `get_environment` לקבלת פרטי סביבת ה-GitHub Actions executor — OS, ארכיטקטורה, CPU, RAM, דיסק וגרסאות כלים.
- `inspect_compute` הוא כלי מקומי של ה-Kaggle worker: מדווח על GPU/VRAM, RAM, דיסקים, הגדרות המודל ומצב llama-server, בלי להחזיר credentials.
- `web_search` מחפש ברשת הציבורית ומחזיר כותרות, קישורים ותקצירים ראשוניים. יש לפתוח ולאמת את המקורות לפני הסתמכות עליהם.

ה-Skills הם הוראות עבודה בלבד; הם אינם מעניקים הרשאות חדשות. פעולות קבצים ופקודות עדיין עוברות דרך שכבת ה-executor. לאחר שינוי Skills או כלים, יש להפעיל מחדש את ה-worker ואת ה-executor כדי שהריצות החדשות יטענו את הקוד המעודכן. ריצות שכבר פעילות ממשיכות עם הגרסה שאיתה התחילו.

בדיקות CI רצות ב-Push וב-Pull Request: בדיקת תחביר Python, בדיקות agent/executor ו-smoke test לממשק.

## מחקר אבטחת קוד מקור

נוסף Workflow נפרד: **Actions → Security source research (Kaggle)**. הוא מיועד לביקורת הגנתית של קוד קיים, למשל Linux Kernel, ולא ליצירת תוכנה.

ברירות המחדל:
- מאגר: `torvalds/linux`, ענף: `master`, תחום: `drivers`.
- מודל: `unsloth/Qwen3.8-27B-GGUF`, קובץ `*UD-Q4_K_M*`, הקשר 16K, עד 40 קריאות כלי מחקר.
- Kaggle מקבל את אותם Secrets קיימים: `KAGGLE_USERNAME` ו-`KAGGLE_API_TOKEN`. Kernel המחקר נוצר כ-private.
- הסוכן מקבל כלים לקריאת קבצים, חיפוש מחרוזות וסריקות סטטיות מוגדרות מראש. הכלים מוגבלים לתת-הספרייה שנבחרה, לקריאה בלבד. אין הרצת קוד מהמאגר, שינוי קבצים או ניסיון ניצול.
- הדוח מכיל commit מדויק, ממצאים, הפניות לקובץ/שורה, רמת ביטחון, השפעה והמלצות תיקון. ממצאי סריקה הם מועמדים לבדיקה — לא הוכחה אוטומטית לפרצה.

**חשוב — פרטיות:** הריפו הזה ציבורי. העלאת הדוח כ-GitHub Artifact כבויה כברירת מחדל, כי הוא עלול להכיל פרטים על חולשות שטרם פורסמו. הפעלה של `publish_report` עלולה לחשוף את הדוח למי שיש לו גישה לריפו. למחקר עם ממצאים רגישים, השתמש בריפו פרטי וביעד אחסון פרטי. גם prompt שהוזן ל-Workflow לא צריך להכיל סודות.

לפני הרצה ראשונה עם Qwen3.8, הרץ פעם אחת את **Build llama.cpp (CUDA, T4)** כדי לוודא שהבינארי שפורסם תומך בארכיטקטורת המודל. אם ההרצה נכשלת בטעינת GGUF, בדוק את `server.log` בפלט Kaggle.

## אבטחה ופרטיות

- **הריפו ציבורי: כל השיחות והקוד גלויים לכולם.** אל תכתוב מידע פרטי.
- ה-worker עונה **רק** להודעות של בעל הריפו. תגובות של אחרים מתעלמים מהן.
- ה-executor מריץ בקשות **רק** מתגובות של `github-actions[bot]` בתוך Issues שנפתחו על ידי בעל הריפו. תגובה של מישהו אחר עם סמן מזויף לא תרוץ, והמוח מקבל תוצאות רק מה-bot.
- הפקודות רצות כמשתמש לינוקס נפרד (`sandbox`), בלי גישה לטוקן, לקבצי ה-runner ולשירות המטא-דאטה של הענן. עדיין אין בידוד מלא: פקודה יכולה להשתמש באינטרנט, ולכן אל תבקש מהמודל להריץ קוד שאתה לא סומך עליו, ואל תכניס סודות לסביבה.
- ה-worker מקבל `GITHUB_TOKEN` של ההרצה שהפעילה אותו: מוגבל לריפו, הרשאת Issues בלבד, ופג בסיום ההרצה. הוא מוטמע במחברת Kaggle **הפרטית**. אל תהפוך אותה לציבורית.
- בתצוגה המקדימה של HTML בדף, הקוד רץ ב-iframe מבודד (sandbox) בלי גישה לטוקן.
- מכסת Kaggle: כ-30 שעות GPU בשבוע, עד 12 שעות לסשן. worker פעיל שומר את ה-GPU תפוס גם כשאין הודעות, ולכן יש כיבוי אוטומטי.

## בדיקות מקומיות

```
python tests/test_runner.py        # חילוץ קוד, היסטוריה, worker, executor ולולאת הסוכן מול GitHub ו-LLM מדומים
python tests/test_security_research.py  # בדיקות כלי מחקר מקור וגבולות נתיבים
npm i jsdom && node tests/ui_smoke.js   # דף הצ'אט (רינדור, XSS, שליחה)
```

## תקלות נפוצות

- `409 Conflict` בדחיפה: יש ריצה פעילה של אותה מחברת, או ש-`KAGGLE_USERNAME` שגוי.
- ההפעלה מהדף נכשלת: חסרה הרשאת *Actions: Read and write* בטוקן.
- ב-GPU אחד בלבד: נסה `NvidiaTeslaT4Highmem` בשדה accelerator.
- "ה-executor לא ענה בזמן": הסביבה כבויה או שהפקודה ארוכה מדי. בדוק את הלשונית Actions.
- שגיאת הקשר (context) מהמודל: הקטן `max_tokens` או הגדל `ctx` ל-32768 ב-**Start chat worker** (ייתכן שלא ייכנס בזיכרון, ואז ראה את `server.log` בפלט).
