# ایجنت روزانه‌ی مقاله — Kaggle → GitHub → سایت

```
Kaggle (GPU، روزانه)  ──commit──►  GitHub (articles/*.json)  ──Action──►  سایت (POST /api/articles/import/)
 ترند + مدل + نگارش فارسی                                                  «در انتظار تایید» ──تایید شما──► منتشر + «مقاله روز»
```

## ۱) سمت سایت (انجام شده)
- آدرس دریافت: `https://kifshow.ir/api/articles/import/` (فقط POST، با هدر `Authorization: Bearer <توکن>`).
- مقاله همیشه **«در انتظار تایید»** ذخیره می‌شود. در پنل مدیریت > مقالات، مقاله را انتخاب کنید و از منوی Action
  گزینه‌ی **«تایید و انتشار»** را بزنید. تا آن موقع فقط مدیر (staff) می‌تواند پیش‌نمایشش را ببیند.
- مقاله‌ی تاییدشده تا ۳ روز در صفحه‌ی اصلی با برچسب **«مقاله روز»** نشان داده می‌شود و وارد sitemap می‌شود.
- سایت قبل از ذخیره بررسی می‌کند: HTML فقط تگ‌های مجاز، فارسی بودن، نبود حروف چینی/ژاپنی/کره‌ای، ۳۵۰ تا ۳۰۰۰ کلمه،
  حداقل ۲ تیتر بخش، نبود Markdown. نگارش فارسی (نیم‌فاصله، ی/ک، ارقام، نقطه‌گذاری) هم خودکار اصلاح می‌شود.
  مقاله‌ی نامعتبر با کد 422 و دلیل رد می‌شود. ارسال دوباره‌ی همان `external_id` مقاله‌ی تکراری نمی‌سازد.
- توکن در فایل `.env` سرور با نام `ARTICLE_IMPORT_TOKEN` است (و نسخه‌ی لوکال آن در `article_agent/.import_token.txt`).

### قالب JSON
```json
{
  "external_id": "2026-10-21-minimal-bag-guide",   // یکتا؛ لاتین
  "title": "…", "slug": "minimal-bag-guide",         // slug لاتین
  "short_description": "…", "seo_title": "…", "seo_description": "…",
  "content_html": "<p>…</p><h2>…</h2>…",             // فقط p h2 h3 ul ol li strong em blockquote a
  "topic": "…", "source_urls": ["https://…"], "model": "Qwen3-32B",
  "cover_image_base64": "…"                          // اختیاری؛ JPEG/PNG/WEBP تا ۱.۵ مگابایت
}
```

## ۲) GitHub (شما)
1. یک ریپوی جدید بسازید (مثلاً `kifshow-articles`). بهتر است **عمومی** باشد، چون مقاله‌ها بالاخره عمومی‌اند.
2. فایل `github_workflow/send-to-site.yml` را در همان ریپو در مسیر `.github/workflows/send-to-site.yml` بگذارید.
3. در Settings > Secrets and variables > Actions دو Secret بسازید:
   - `SITE_IMPORT_URL` = `https://kifshow.ir/api/articles/import/`
   - `SITE_IMPORT_TOKEN` = محتوای `article_agent/.import_token.txt`
4. برای Kaggle یک **Fine-grained token** بسازید: فقط همین ریپو، دسترسی *Contents: Read and write*.

## ۳) Kaggle (شما)
1. Notebook جدید؛ Settings: **Accelerator = GPU T4 x2** (یا P100)، **Internet = On** (نیازمند تایید شماره تلفن).
2. Add-ons > Secrets: `GITHUB_TOKEN`، `GITHUB_REPO` (مثل `masoudshahrian/kifshow-articles`)، و اختیاری `HF_TOKEN`.
3. محتوای `kaggle_daily_article.py` را در Notebook بچسبانید.
4. **اول آزمون مدل‌ها:** `MODE = "eval"` بگذارید و Run کنید. هر مدل ۳ مقاله می‌نویسد و فایل‌های HTML در
   `/kaggle/working/eval` ذخیره می‌شود. آن‌ها را بخوانید و مدلی را که فارسی‌اش بهتر است اول `MODEL_CANDIDATES` بگذارید.
5. بعد `MODE = "publish"` و ابتدا یک بار `DRY_RUN = True` (فقط می‌سازد، نمی‌فرستد). اگر خروجی خوب بود `DRY_RUN = False`.
6. اجرای روزانه: Save Version > Save & Run All، سپس Schedule = Daily.
   **توجه:** برخی منابع می‌گویند زمان‌بندی Kaggle فقط CPU را پشتیبانی می‌کند. اگر برای حساب شما GPU مجاز نبود،
   روش جایگزین: یک Action زمان‌بندی‌شده در GitHub با دستور `kaggle kernels push` (با GPU) — بگویید تا بنویسم.

## نکته‌ها
- فقط **یک مقاله در روز**؛ اگر مقاله‌ی امروز قبلاً ساخته شده باشد، اجرا بدون کار خارج می‌شود.
- موضوع‌های تکراری (۶۰ موضوع اخیر) رد می‌شوند. فایل حافظه: `state/used_topics.json` در همان ریپوی GitHub.
- اگر ترند مرتبطی نبود، از ۱۵ موضوع همیشگی استفاده می‌شود.
- مقاله‌ی نامعتبر هرگز فرستاده نمی‌شود؛ بعد از ۳ تلاش، نوت‌بوک با خطا تمام می‌شود و در Kaggle می‌بینید.
- تصویر کاور فعلاً یک طرح ساده‌ی خودکار است؛ پیش از تایید می‌توانید از پنل عکس بهتری جایگزین کنید.
