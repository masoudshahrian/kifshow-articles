# -*- coding: utf-8 -*-
"""
ایجنت روزانه‌ی مقاله‌نویسی کیف‌شو — برای اجرا در Kaggle Notebook (GPU فعال، Internet روشن).

مسیر کار:
  ترند روز (Google Trends RSS + Google News + مجله‌های مد)  ->  فیلتر کیف و مد  ->  حذف موضوع تکراری
  ->  انتخاب موضوع با مدل  ->  نوشتن مقاله‌ی فارسی (HTML)  ->  اصلاح نگارش فارسی  ->  بررسی کیفیت
  ->  ساخت تصویر کاور  ->  commit فایل JSON در ریپوی GitHub (پوشه‌ی articles/)
بعد از آن GitHub Action فایل را به سایت می‌فرستد و سایت آن را «در انتظار تایید» می‌گذارد.

راه‌اندازی (یک‌بار):
  1) در Kaggle یک Notebook جدید بسازید؛ Settings: Accelerator = GPU T4 x2 (یا P100)، Internet = On
     (روشن شدن اینترنت نیاز به تایید شماره تلفن حساب Kaggle دارد).
  2) Add-ons > Secrets و این‌ها را بسازید:
        GITHUB_TOKEN  توکن GitHub (Fine-grained، فقط روی ریپوی خروجی، دسترسی Contents: Read and write)
        GITHUB_REPO   مثال:  masoudshahrian/kifshow-articles
        HF_TOKEN      (اختیاری؛ فقط برای مدل‌هایی مثل Gemma که پذیرش مجوز می‌خواهند)
  3) کل این فایل را در یک سلول بچسبانید (یا هر بخش «# %%» را در یک سلول جدا) و Run کنید.
  4) برای اجرای روزانه: Save Version > Save & Run All، و بعد در تنظیمات همان Notebook گزینه‌ی Schedule
     را روی Daily بگذارید. اگر زمان‌بندی GPU برای حساب شما فعال نبود، روش جایگزین در README.md آمده است.

حالت‌های اجرا (متغیر MODE):
  "publish"  تولید مقاله‌ی امروز و ارسال به GitHub (پیش‌فرض)
  "eval"     آزمون چند مدل روی ۳ موضوع ثابت؛ خروجی در /kaggle/working/eval برای مقایسه‌ی کیفیت فارسی
"""
# %% ---------------------------------------------------------------- تنظیمات
import base64
import datetime as dt
import gc
import hashlib
import html
import io
import json
import os
import random
import re
import subprocess
import sys
import time

MODE = "publish"            # "publish" یا "eval"
DRY_RUN = False             # True = فقط تولید و ذخیره در /kaggle/working، بدون ارسال به GitHub
PROOFREAD = True            # یک دور بازنویسی برای رفع غلط‌های نگارشی (زمان اجرا را حدود دو برابر می‌کند)
MAKE_COVER = True           # ساخت تصویر کاور ساده
MAX_ATTEMPTS = 3            # تعداد تلاش برای تولید مقاله‌ی معتبر
DEDUP_LAST_N = 60           # موضوع تازه نباید شبیه ۶۰ موضوع اخیر باشد

# مدل‌ها به ترتیب اولویت؛ اگر یکی بارگذاری نشد، بعدی امتحان می‌شود.
# نسخه‌های bnb-4bit از قبل کوانتیزه‌اند: دانلود کمتر (حدود ۱۵ تا ۲۰ گیگ) و جا شدن روی T4 x2.
# نام مخزن‌ها را قبل از اجرا در huggingface.co بررسی کنید؛ اگر عوض شده بود، همین‌جا اصلاح کنید.
MODEL_CANDIDATES = [
    "unsloth/Qwen3-32B-bnb-4bit",
    "unsloth/gemma-3-27b-it-bnb-4bit",
    "unsloth/Qwen3-14B-bnb-4bit",
]
EVAL_MODELS = MODEL_CANDIDATES  # در حالت eval همه‌ی این‌ها آزموده می‌شوند

SITE_SHOP_URL = "/shop/"
INTERNAL_GUIDES = {   # مقاله‌های موجود سایت برای لینک داخلی
    "عطر و ادکلن": "/blog/perfume-guide/", "عینک": "/blog/eyeglasses-guide/", "لباس": "/blog/clothing-guide/",
    "ساعت": "/blog/watch-guide/", "اکسسوری": "/blog/accessories-guide/", "لوازم آرایش": "/blog/makeup-guide/",
}

EVERGREEN_TOPICS = [   # اگر ترند مرتبطی پیدا نشد، از این موضوع‌های همیشگی استفاده می‌شود
    "راهنمای نگهداری و تمیز کردن کیف چرم طبیعی",
    "تفاوت چرم طبیعی و چرم مصنوعی و روش تشخیص آن‌ها",
    "چطور کیف مناسب هر موقعیت را انتخاب کنیم؟ کار، سفر و مهمانی",
    "کیف کوله‌ای یا دوشی؟ انتخاب مناسب بر اساس سبک زندگی",
    "ست کردن رنگ کیف و کفش در پاییز و زمستان",
    "کیف‌های مینیمال و دلیل محبوبیت آن‌ها",
    "چند کیف برای یک کمد کاربردی کافی است؟",
    "نکات خرید کیف چرم از فروشگاه اینترنتی",
    "روش‌های جلوگیری از چروک و ترک خوردن کیف",
    "کیف مجلسی مناسب مهمانی: رنگ، اندازه و جنس",
    "کیف اسپرت و ورزشی؛ چه ویژگی‌هایی مهم است؟",
    "راهنمای انتخاب اندازه‌ی کیف بر اساس وسایل روزانه",
    "تاریخچه‌ی کیف‌دستی و تغییر مد آن در قرن اخیر",
    "کیف مردانه‌ی اداری؛ چه مدلی بخریم؟",
    "اشتباهات رایج هنگام خرید کیف",
]

FASHION_KEYWORDS = [
    "bag", "handbag", "purse", "tote", "clutch", "backpack", "satchel", "crossbody", "wallet", "leather",
    "fashion", "style", "outfit", "wardrobe", "runway", "collection", "accessor", "sneaker", "shoe", "boot",
    "dress", "coat", "jacket", "trend", "vogue", "chanel", "gucci", "prada", "dior", "hermes", "hermès",
    "louis vuitton", "balenciaga", "fendi", "celine", "loewe", "bottega", "miu miu", "ysl", "saint laurent",
    "fashion week", "met gala", "watch", "sunglasses", "jewel", "perfume", "makeup",
    "کیف", "مد", "لباس", "چرم", "استایل", "کفش",
]

TREND_GEOS = ["US", "GB", "FR", "IT", "DE", "TR", "AE", "IR"]
FASHION_FEEDS = [
    "https://www.vogue.com/feed/rss",
    "https://www.elle.com/rss/all.xml/",
    "https://www.harpersbazaar.com/rss/all.xml/",
    "https://hypebeast.com/feed",
    "https://www.whowhatwear.com/rss",
]
NEWS_QUERIES = [
    "handbag OR \"leather bag\" OR \"tote bag\" when:2d",
    "fashion trend bag when:2d",
    "\"fashion week\" bag when:3d",
]
UA = {"User-Agent": "Mozilla/5.0 (compatible; KifshowTrendBot/1.0)"}


# %% ---------------------------------------------------------------- ابزار عمومی
def ensure_deps():
    pkgs = ["transformers>=4.51", "accelerate", "bitsandbytes>=0.43", "feedparser", "requests", "Pillow"]
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", *pkgs], check=False)


def get_secret(name, default=""):
    try:
        from kaggle_secrets import UserSecretsClient
        return UserSecretsClient().get_secret(name)
    except Exception:
        return os.environ.get(name, default)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---- نگارش فارسی (همان قواعد سایت: apps/blog/persian.py)
ZWNJ = "‌"
_FA = "؀-ۿ"
_CHAR_MAP = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "٠": "۰", "١": "۱", "٢": "۲", "٣": "۳", "٤": "۴",
                           "٥": "۵", "٦": "۶", "٧": "۷", "٨": "۸", "٩": "۹"})
_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_DIGITS_RE = re.compile(r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)*(?![A-Za-z0-9])")
_MI_RE = re.compile(rf"(?<![{_FA}])(ن?می)[ \t]+(?=[{_FA}])")
_SUFFIX_RE = re.compile(rf"(?<=[{_FA}])[ \t]+(ها|های|هایی|هایم|هایت|هایش|ترین|تر)(?![{_FA}])")
_QUOTE_RE = re.compile(r'"([^"\n]*[؀-ۿ][^"\n]*)"')


def normalize_persian(text):
    if not text:
        return text
    t = text.translate(_CHAR_MAP)
    t = _DIGITS_RE.sub(lambda m: m.group(0).translate(_DIGITS).replace(".", "٫").replace(",", "٬"), t)
    t = re.sub(rf"(?<=[{_FA}])[ \t]+(?=[,;?])", "", t)
    t = re.sub(rf"(?<=[{_FA}]),", "،", t)
    t = re.sub(rf"(?<=[{_FA}]);", "؛", t)
    t = re.sub(rf"(?<=[{_FA}])\?", "؟", t)
    t = t.replace("...", "…")
    t = _QUOTE_RE.sub(r"«\1»", t)
    t = re.sub(r"[ \t]+([،؛؟!:.\)»])", r"\1", t)
    t = re.sub(r"([،؛؟!])(?=[A-Za-z؀-ۿ«(])", r"\1 ", t)
    t = _MI_RE.sub(lambda m: m.group(1) + ZWNJ, t)
    t = _SUFFIX_RE.sub(lambda m: ZWNJ + m.group(1), t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(f"{ZWNJ}{{2,}}", ZWNJ, t)
    return re.sub(f"{ZWNJ}(?=[ \n])|(?<=[ \n]){ZWNJ}", "", t)


def persian_ratio(text):
    fa = len(re.findall(r"[؀-ۿ]", text))
    en = len(re.findall(r"[A-Za-z]", text))
    return fa / (fa + en) if fa + en else 0.0


CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")
ALLOWED_TAGS = {"p", "h2", "h3", "ul", "ol", "li", "strong", "em", "blockquote", "br", "a"}


def clean_model_html(raw):
    """خروجی مدل را به HTML ساده تبدیل می‌کند (حذف ```، تگ‌های ناخواسته و نشانه‌های Markdown رایج)."""
    t = re.sub(r"^```(?:html)?\s*|\s*```$", "", raw.strip(), flags=re.M)
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.S)
    t = re.sub(r"(?m)^\s*###\s+(.+)$", r"<h3>\1</h3>", t)
    t = re.sub(r"(?m)^\s*##\s+(.+)$", r"<h2>\1</h2>", t)
    t = re.sub(r"(?m)^\s*#\s+(.+)$", r"<h2>\1</h2>", t)
    t = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"</?(h1)>", lambda m: m.group(0).replace("h1", "h2"), t)

    def keep(m):
        return m.group(0) if m.group(1).lower() in ALLOWED_TAGS else ""
    t = re.sub(r"</?([a-zA-Z0-9]+)[^>]*>", keep, t)
    return t.strip()


def quality_problems(title, content_html):
    """همان بررسی‌های سایت؛ فهرست مشکلات (خالی = سالم)."""
    problems = []
    text = html.unescape(re.sub(r"<[^>]+>", " ", content_html))
    words = len(text.split())
    if not 350 <= words <= 3000:
        problems.append(f"تعداد کلمات {words}")
    if CJK_RE.search(text) or CJK_RE.search(title):
        problems.append("حروف چینی/ژاپنی/کره‌ای")
    if persian_ratio(text) < 0.7:
        problems.append("نسبت متن فارسی پایین")
    if persian_ratio(title) < 0.5:
        problems.append("عنوان فارسی نیست")
    if content_html.count("<h2>") < 2:
        problems.append("کمتر از دو h2")
    if re.search(r"```|(^|\n)\s*#{1,6}\s", content_html):
        problems.append("Markdown")
    return problems


# %% ---------------------------------------------------------------- ترند
def _norm_tokens(s):
    return {w for w in re.findall(r"[a-z0-9؀-ۿ]+", (s or "").lower()) if len(w) > 2}


def _is_fashion(text):
    t = (text or "").lower()
    return any(k in t for k in FASHION_KEYWORDS)


def collect_candidates():
    import feedparser
    import requests
    cands = []

    def add(title, source, url="", summary="", weight=1.0):
        title = re.sub(r"\s+", " ", (title or "")).strip()
        if title:
            cands.append({"title": title, "source": source, "url": url,
                          "summary": re.sub(r"<[^>]+>", " ", summary or "")[:300].strip(), "weight": weight})

    # ۱) جستجوهای ترند گوگل (فقط موردهای مرتبط با مد/کیف نگه داشته می‌شوند)
    for geo in TREND_GEOS:
        try:
            feed = feedparser.parse(requests.get(f"https://trends.google.com/trending/rss?geo={geo}",
                                                 headers=UA, timeout=20).content)
            for e in feed.entries:
                blob = " ".join(str(v) for k, v in e.items() if isinstance(v, str))
                if _is_fashion(blob):
                    add(e.get("title", ""), f"google-trends:{geo}", e.get("link", ""), blob, 2.0)
            log(f"trends {geo}: {len(feed.entries)} entries")
        except Exception as exc:
            log(f"trends {geo} failed: {exc}")

    # ۲) خبر گوگل برای کیف و مد
    from urllib.parse import quote
    for q in NEWS_QUERIES:
        try:
            url = f"https://news.google.com/rss/search?q={quote(q)}&hl=en-US&gl=US&ceid=US:en"
            feed = feedparser.parse(requests.get(url, headers=UA, timeout=20).content)
            for e in feed.entries[:15]:
                add(e.get("title", ""), "google-news", e.get("link", ""), e.get("summary", ""), 1.5)
            log(f"news '{q[:25]}': {len(feed.entries)} entries")
        except Exception as exc:
            log(f"news failed: {exc}")

    # ۳) مجله‌های مد
    for url in FASHION_FEEDS:
        try:
            feed = feedparser.parse(requests.get(url, headers=UA, timeout=20).content)
            for e in feed.entries[:10]:
                add(e.get("title", ""), url.split("/")[2], e.get("link", ""), e.get("summary", ""), 1.0)
            log(f"feed {url.split('/')[2]}: {len(feed.entries)} entries")
        except Exception as exc:
            log(f"feed {url} failed: {exc}")

    # امتیاز بیشتر برای موردهای مرتبط با کیف
    for c in cands:
        if re.search(r"\b(bag|handbag|purse|tote|clutch|backpack|satchel|crossbody|wallet)\b",
                     (c["title"] + " " + c["summary"]).lower()):
            c["weight"] += 2.0
    cands.sort(key=lambda c: -c["weight"])
    return cands


def is_duplicate(topic_text, used):
    a = _norm_tokens(topic_text)
    for u in used[-DEDUP_LAST_N:]:
        b = _norm_tokens(u.get("topic", "") + " " + u.get("title", ""))
        if a and b and len(a & b) / len(a | b) >= 0.5:
            return True
    return False


# %% ---------------------------------------------------------------- GitHub
class GitHubRepo:
    def __init__(self, repo, token):
        import requests
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28"})
        self.base = f"https://api.github.com/repos/{repo}/contents"

    def get(self, path):
        r = self.s.get(f"{self.base}/{path}", timeout=30)
        if r.status_code == 404:
            return None, None
        r.raise_for_status()
        j = r.json()
        return base64.b64decode(j["content"]).decode("utf-8"), j["sha"]

    def put(self, path, text, message, sha=None):
        body = {"message": message, "content": base64.b64encode(text.encode("utf-8")).decode()}
        if sha:
            body["sha"] = sha
        r = self.s.put(f"{self.base}/{path}", json=body, timeout=60)
        r.raise_for_status()
        return r.json()


# %% ---------------------------------------------------------------- مدل
_MODEL = {"name": None, "tok": None, "model": None}


def load_model(candidates):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    for d in ("/kaggle/temp", "/kaggle/tmp", "/tmp"):
        if os.path.isdir(d):
            os.environ.setdefault("HF_HOME", os.path.join(d, "hf"))
            break
    token = get_secret("HF_TOKEN") or None
    for name in candidates:
        try:
            log("loading", name)
            tok = AutoTokenizer.from_pretrained(name, token=token)
            model = AutoModelForCausalLM.from_pretrained(name, device_map="auto", torch_dtype=torch.float16, token=token)
            model.eval()
            _MODEL.update(name=name, tok=tok, model=model)
            log("loaded", name, "| GPUs:", torch.cuda.device_count())
            return
        except Exception as exc:
            log(f"could not load {name}: {type(exc).__name__}: {str(exc)[:200]}")
            unload_model()
    raise RuntimeError("هیچ‌کدام از مدل‌ها بارگذاری نشد؛ نام مخزن‌ها و Accelerator را بررسی کنید.")


def unload_model():
    import torch
    _MODEL.update(name=None, tok=None, model=None)
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def chat(system, user, max_new_tokens=4500, temperature=0.7):
    import torch
    tok, model = _MODEL["tok"], _MODEL["model"]
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    except TypeError:
        prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    except Exception:  # برخی مدل‌ها نقش system را نمی‌پذیرند
        msgs = [{"role": "user", "content": system + "\n\n" + user}]
        prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inputs = tok(prompt, return_tensors="pt", add_special_tokens=False).to(model.device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=True, temperature=temperature,
                             top_p=0.9, repetition_penalty=1.05)
    text = tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


# %% ---------------------------------------------------------------- پرامپت‌ها
STYLE_GUIDE = """قواعد نگارش فارسی (حتماً رعایت کن):
- فارسی معیار و روان بنویس؛ جمله‌های کوتاه تا متوسط. از ترجمه‌ی تحت‌اللفظی بپرهیز.
- نیم‌فاصله: «می‌شود»، «نمی‌دانم»، «کیف‌ها»، «بزرگ‌ترین»، «به‌عنوان». حروف «ی» و «ک» فارسی (نه «ي» و «ك» عربی).
- نقطه‌گذاری فارسی: ویرگول «،» ، نقطه‌ویرگول «؛» ، علامت سؤال «؟» ، نقل‌قول با «گیومه».
- ارقام فارسی (۱ ۲ ۳). نام برندها و کدهایی مثل UV400 می‌توانند لاتین بمانند.
- کلمه‌های انگلیسی را تا حد ممکن فارسی کن؛ اگر اصطلاح رایج است بار اول معادل فارسی بنویس و در پرانتز انگلیسی‌اش را بیاور.
- هرگز از حروف چینی، ژاپنی یا کره‌ای استفاده نکن."""

WRITER_SYSTEM = f"""تو نویسنده‌ی وبلاگ یک فروشگاه اینترنتی ایرانی کیف و مصنوعات چرمی (کیف‌شو) هستی. مخاطب، خریدار ایرانی است.
لحن: صمیمی، حرفه‌ای و بدون اغراق. هدف: مقاله‌ای مفید و واقعی که خواننده را در انتخاب و نگهداری کیف و استایل کمک کند.

{STYLE_GUIDE}

قواعد محتوا:
- هیچ قیمت، آمار، نقل‌قول، نام طراح، تاریخ یا ادعای علمی اختراع نکن. فقط چیزهایی را بگو که در «منابع» آمده یا دانش عمومی و قطعی است.
- مقاله باید «راهنمای کاربردی» باشد (نه خبر): از ترند فقط به‌عنوان بهانه‌ی موضوع استفاده کن و یک بار بنویس «این روزها».
- طول: ۶۵۰ تا ۸۰۰ کلمه.
- ساختار: ۲ پاراگراف مقدمه؛ سپس ۴ تا ۵ بخش با تیتر <h2> (هر کدام ۱ تا ۲ پاراگراف یا یک فهرست، در صورت نیاز با زیرتیتر <h3>)؛ یک بخش <h2>پرسش‌های متداول</h2> با ۳ پرسش (پرسش در <strong>)؛ جمع‌بندی کوتاه.
- فقط این تگ‌های HTML: p, h2, h3, ul, ol, li, strong, em, blockquote, a. تگ h1، Markdown (# و **)، و ``` ممنوع است.
- دو لینک داخلی بگذار: <a href="{SITE_SHOP_URL}">محصولات کیف‌شو</a> و یکی از مقاله‌های مرتبط از این فهرست: {json.dumps(INTERNAL_GUIDES, ensure_ascii=False)}.

قالب خروجی دقیقاً این باشد (بدون هیچ توضیح اضافه):
TITLE: عنوان فارسی جذاب (حداکثر ۷۰ نویسه)
SEO_TITLE: عنوان سئو (حداکثر ۶۰ نویسه)
SEO_DESCRIPTION: توضیح سئو (۱۲۰ تا ۱۶۰ نویسه)
SHORT: خلاصه‌ی یک‌جمله‌ای (حداکثر ۲۵۰ نویسه)
SLUG: english-short-slug-with-dashes
---HTML---
(متن مقاله به‌صورت HTML)"""

PICKER_SYSTEM = """تو سردبیر وبلاگ یک فروشگاه ایرانی کیف و مد هستی. از فهرست ترندهای امروز، «یک» مورد را انتخاب کن که بیشترین ارتباط
با کیف، چرم، اکسسوری یا استایل را دارد و بتوان از آن یک راهنمای مفید برای خریدار ایرانی نوشت.
فقط یک شیء JSON برگردان: {"index": عدد, "topic_fa": "موضوع به فارسی", "angle": "زاویه‌ی مقاله به فارسی در یک جمله"}
اگر هیچ مورد مرتبطی نیست: {"index": -1}"""

PROOF_SYSTEM = f"""تو ویراستار حرفه‌ای فارسی هستی. متن HTML زیر را فقط از نظر نگارش و روانی ویرایش کن:
غلط‌های املایی و دستوری، جمله‌های ناروان یا ترجمه‌ای، نیم‌فاصله و نقطه‌گذاری.
معنا، ساختار، تگ‌ها، لینک‌ها و طول متن را تغییر نده و چیزی اضافه یا کم نکن. فقط HTML ویرایش‌شده را برگردان.

{STYLE_GUIDE}"""


def parse_article(raw):
    head, _, body = raw.partition("---HTML---")
    if not body:
        raise ValueError("جداکننده‌ی ---HTML--- پیدا نشد")

    def field(name):
        m = re.search(rf"^{name}:\s*(.+)$", head, re.M)
        return m.group(1).strip() if m else ""
    return {"title": field("TITLE"), "seo_title": field("SEO_TITLE"), "seo_description": field("SEO_DESCRIPTION"),
            "short_description": field("SHORT"), "slug": field("SLUG").lower(), "content_html": clean_model_html(body)}


def pick_topic(cands, used):
    fresh = [c for c in cands if not is_duplicate(c["title"], used)][:12]
    if fresh:
        listing = "\n".join(f"{i}. {c['title']} — {c['summary'][:150]}" for i, c in enumerate(fresh))
        try:
            raw = chat(PICKER_SYSTEM, listing, max_new_tokens=300, temperature=0.3)
            m = re.search(r"\{.*\}", raw, re.S)
            data = json.loads(m.group(0)) if m else {}
            idx = int(data.get("index", -1))
            if 0 <= idx < len(fresh) and data.get("topic_fa"):
                c = fresh[idx]
                return {"topic": data["topic_fa"], "angle": data.get("angle", ""), "sources": [c]}
        except Exception as exc:
            log("picker failed:", exc)
    pool = [t for t in EVERGREEN_TOPICS if not is_duplicate(t, used)] or EVERGREEN_TOPICS
    topic = pool[dt.date.today().toordinal() % len(pool)]
    log("no relevant trend; using evergreen topic:", topic)
    return {"topic": topic, "angle": "راهنمای کاربردی", "sources": []}


def write_article(choice, temperature):
    src = "\n".join(f"- {c['title']} ({c['source']}): {c['summary']}" for c in choice["sources"]) or "- (بدون منبع؛ موضوع همیشگی)"
    user = (f"موضوع مقاله: {choice['topic']}\nزاویه: {choice['angle']}\n\nمنابع (برای الهام؛ از خودشان نقل نکن):\n{src}\n\n"
            "مقاله را با همان قالب خروجی بنویس.")
    art = parse_article(chat(WRITER_SYSTEM, user, temperature=temperature))
    if PROOFREAD:
        try:
            fixed = clean_model_html(chat(PROOF_SYSTEM, art["content_html"], temperature=0.2))
            if len(fixed.split()) >= 0.8 * len(art["content_html"].split()):   # ویرایش نباید متن را کوتاه کند
                art["content_html"] = fixed
        except Exception as exc:
            log("proofread skipped:", exc)
    for k in ("title", "seo_title", "seo_description", "short_description", "content_html"):
        art[k] = normalize_persian(art[k])
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", art["slug"] or ""):
        art["slug"] = "article-" + hashlib.md5(art["title"].encode()).hexdigest()[:8]
    return art


# %% ---------------------------------------------------------------- تصویر کاور
def make_cover_b64(seed_text):
    """کاور ساده‌ی ۱۶۰۰×۸۰۰: گرادیان رنگی + طرح خطی کیف (بدون متن، پس مشکل فونت فارسی ندارد)."""
    from PIL import Image, ImageDraw
    h = int(hashlib.md5(seed_text.encode()).hexdigest(), 16)
    palettes = [((44, 24, 16), (110, 62, 44)), ((22, 30, 44), (62, 82, 112)), ((38, 26, 40), (100, 62, 90)),
                ((20, 28, 26), (52, 82, 72)), ((44, 30, 14), (122, 88, 40)), ((54, 20, 30), (136, 56, 72))]
    c1, c2 = palettes[h % len(palettes)]
    S, W, H = 2, 1600, 800
    w, hh = W * S, H * S
    img = Image.new("RGB", (w // 8, hh // 8))
    px = img.load()
    for y in range(hh // 8):
        for x in range(w // 8):
            t = x / (w // 8) * 0.6 + y / (hh // 8) * 0.4
            px[x, y] = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
    img = img.resize((w, hh)).convert("RGBA")
    d = ImageDraw.Draw(img)
    gold, lw = (214, 196, 128), 10 * S
    cx, cy, u = w / 2, hh / 2 + 40 * S, 300 * S
    m = 36 * S
    d.rounded_rectangle((m, m, w - m, hh - m), radius=40 * S, outline=(214, 196, 128, 90), width=2 * S)
    d.rounded_rectangle((cx - u * 0.95, cy - u * 0.35, cx + u * 0.95, cy + u * 0.75), radius=60 * S, outline=gold, width=lw)
    d.arc((cx - u * 0.55, cy - u * 0.95, cx + u * 0.55, cy + u * 0.15), 180, 360, fill=gold, width=lw)
    d.rounded_rectangle((cx - u * 0.14, cy - u * 0.12, cx + u * 0.14, cy + u * 0.16), radius=14 * S, outline=gold, width=lw // 2)
    img = img.resize((W, H)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=86, optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


# %% ---------------------------------------------------------------- اجرای اصلی
def generate_valid_article(choice):
    last = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        temp = 0.65 + 0.1 * (attempt - 1)
        log(f"writing article (attempt {attempt}, T={temp:.2f})")
        try:
            art = write_article(choice, temp)
        except Exception as exc:
            last = [f"parse: {exc}"]
            log("attempt failed:", last)
            continue
        last = quality_problems(art["title"], art["content_html"])
        if not last:
            return art
        log("quality problems:", last)
    raise RuntimeError(f"مقاله‌ی معتبر تولید نشد: {last}")


def run_publish():
    repo = get_secret("GITHUB_REPO")
    token = get_secret("GITHUB_TOKEN")
    if not DRY_RUN and not (repo and token):
        raise RuntimeError("Secretهای GITHUB_REPO و GITHUB_TOKEN را در Kaggle تنظیم کنید.")
    gh = GitHubRepo(repo, token) if not DRY_RUN else None

    state_text, state_sha = (gh.get("state/used_topics.json") if gh else (None, None))
    used = json.loads(state_text) if state_text else []

    today = dt.date.today().isoformat()
    if any(u.get("date") == today for u in used):
        log("مقاله‌ی امروز قبلاً ساخته شده است؛ خروج.")
        return

    cands = collect_candidates()
    log("candidates:", len(cands))
    load_model(MODEL_CANDIDATES)
    choice = pick_topic(cands, used)
    log("topic:", choice["topic"])
    art = generate_valid_article(choice)

    payload = {
        "external_id": f"{today}-{art['slug']}"[:100], "title": art["title"], "slug": art["slug"],
        "short_description": art["short_description"], "seo_title": art["seo_title"],
        "seo_description": art["seo_description"], "content_html": art["content_html"],
        "topic": choice["topic"], "source_urls": [c["url"] for c in choice["sources"] if c.get("url")],
        "model": _MODEL["name"], "language": "fa", "generated_at": dt.datetime.utcnow().isoformat() + "Z",
    }
    if MAKE_COVER:
        payload["cover_image_base64"] = make_cover_b64(choice["topic"])

    os.makedirs("/kaggle/working/out", exist_ok=True)
    fname = f"{today}-{art['slug']}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    open(f"/kaggle/working/out/{fname}", "w", encoding="utf-8").write(text)
    log("saved locally:", fname, "| words:", len(re.sub(r"<[^>]+>", " ", art["content_html"]).split()))

    if DRY_RUN:
        log("DRY_RUN: به GitHub ارسال نشد.")
        return
    gh.put(f"articles/{fname}", text, f"article: {art['title'][:60]}")
    used.append({"date": today, "topic": choice["topic"], "title": art["title"]})
    gh.put("state/used_topics.json", json.dumps(used[-300:], ensure_ascii=False, indent=2),
           f"state: {today}", sha=state_sha)
    log("pushed to GitHub:", fname)


EVAL_TOPICS = [
    {"topic": "چطور کیف چرم طبیعی را از چرم مصنوعی تشخیص دهیم؟", "angle": "راهنمای خرید", "sources": []},
    {"topic": "ترند کیف‌های مینیمال و کوچک در مد امروز", "angle": "چرا محبوب شده و چطور انتخاب کنیم", "sources": []},
    {"topic": "نگهداری کیف چرم در زمستان و رطوبت", "angle": "نکات عملی نگهداری", "sources": []},
]


def run_eval():
    os.makedirs("/kaggle/working/eval", exist_ok=True)
    rows = []
    for name in EVAL_MODELS:
        try:
            load_model([name])
        except Exception as exc:
            rows.append((name, "load failed", str(exc)[:80]))
            continue
        for i, choice in enumerate(EVAL_TOPICS, 1):
            t0 = time.time()
            try:
                art = write_article(choice, 0.7)
                problems = quality_problems(art["title"], art["content_html"])
                words = len(re.sub(r"<[^>]+>", " ", art["content_html"]).split())
                safe = re.sub(r"[^A-Za-z0-9]+", "_", name)
                open(f"/kaggle/working/eval/{safe}_{i}.html", "w", encoding="utf-8").write(
                    f"<meta charset='utf-8'><div dir='rtl' style='font-family:Tahoma;max-width:800px;margin:auto'>"
                    f"<h1>{art['title']}</h1>{art['content_html']}</div>")
                rows.append((name, f"topic {i}", f"{words} words, {time.time() - t0:.0f}s, problems={problems or 'none'}"))
            except Exception as exc:
                rows.append((name, f"topic {i}", f"error: {str(exc)[:80]}"))
        unload_model()
    print("\n=== نتیجه‌ی آزمون مدل‌ها ===")
    for r in rows:
        print(" | ".join(r))
    print("فایل‌های HTML در /kaggle/working/eval ذخیره شد؛ آن‌ها را دانلود و کیفیت فارسی را مقایسه کنید.")


def main():
    ensure_deps()
    run_eval() if MODE == "eval" else run_publish()


if __name__ == "__main__":
    main()
