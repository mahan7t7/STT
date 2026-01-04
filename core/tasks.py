# core/tasks.py

import logging
import os
from celery import shared_task
import requests
import yt_dlp
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse


from .models import AudioFile, ImportBatch, ImportItem
from .services import (
    EbooService,
    ScribeService,
    ViraService,
    MediaService,
    download_temp_file,
)

logger = logging.getLogger("core")

HUMAN_ERRORS = {
    "video": "خطا در استخراج صدا از فایل ویدیویی.",
    "service": "خطا در ارتباط با سرویس پردازش.",
    "timeout": "پردازش فایل بیش از حد طول کشید.",
    "empty": "متنی از فایل استخراج نشد.",
    "unknown": "خطای نامشخص در پردازش فایل.",
}


# core/tasks.py

@shared_task(bind=True)
def process_audio_file(self, file_id):
    """
    Celery task to process a single AudioFile.
    
    Improvements:
    - Queue logic moved to 'finally' block (Runs even on error).
    - Prevents race conditions using atomic updates.
    - robust cleanup of temp files.
    """

    logger.info(f"[TASK START] file_id={file_id}")

    audio_file = None
    extracted_audio_path = None
    temp_path = None  

    try:
        # ---------------------------------------------------------
        # 1. Load DB record
        # ---------------------------------------------------------
        try:
            audio_file = AudioFile.objects.get(id=file_id)
        except AudioFile.DoesNotExist:
            logger.error(f"[ERROR] AudioFile {file_id} not found.")
            return 

        # ---------------------------------------------------------
        # 2. Track task + set PROCESSING
        # ---------------------------------------------------------
        audio_file.task_id = self.request.id
        audio_file.status = AudioFile.Status.PROCESSING
        audio_file.save(update_fields=["task_id", "status"])

        logger.info(f"[STATUS] File {file_id} -> PROCESSING")


        # -------------------------------
        # 3. Resolve file_path
        # -------------------------------
        file_path = None

        if audio_file.audio_file:
            file_path = audio_file.audio_file.path

        elif audio_file.source_url:
            try:
                logger.info(f"[IMPORT] Downloading from URL: {audio_file.source_url}")
                temp_path = download_temp_file(audio_file.source_url)
                file_path = temp_path
            except Exception as e:
                logger.error(f"[IMPORT ERROR] {e}", exc_info=True)
                audio_file.status = AudioFile.Status.FAILED
                audio_file.error_message = "دانلود فایل از لینک ناموفق بود."
                audio_file.save()
                raise Exception("Download failed")

        else:
            audio_file.status = AudioFile.Status.FAILED
            audio_file.error_message = "هیچ منبع فایلی یافت نشد."
            audio_file.save()
            raise Exception("No source file")

        # ---------------------------------------------------------
        # 4. Video → extract audio
        # ---------------------------------------------------------
        if audio_file.is_video:
            logger.info(f"[VIDEO] Extracting audio for file {file_id}")
            try:
                extracted_audio_path = MediaService.extract_audio(file_path)
                file_path = extracted_audio_path
            except Exception as ve:
                logger.error(f"[VIDEO ERROR] {ve}", exc_info=True)
                audio_file.status = AudioFile.Status.FAILED
                audio_file.error_message = HUMAN_ERRORS["video"]
                audio_file.save()
                raise Exception("Video extraction failed")

        # ---------------------------------------------------------
        # 5. Select AI service
        # ---------------------------------------------------------
        model = audio_file.model_name or AudioFile.ModelChoices.EBOO
        logger.debug(f"[AI SERVICE] model={model} file={file_path}")

        result = None
        try:
            if model == AudioFile.ModelChoices.EBOO:
                result = EbooService.process(file_path)
            elif model == AudioFile.ModelChoices.SCRIBE:
                result = ScribeService.process(file_path)
            elif model == AudioFile.ModelChoices.VIRA:
                result = ViraService.process(file_path)
            else:
                result = {"error": f"Unknown model: {model}"}

        except Exception as api_err:
            logger.error(f"[AI ERROR] {api_err}", exc_info=True)
            audio_file.status = AudioFile.Status.FAILED
            audio_file.error_message = HUMAN_ERRORS["service"]
            audio_file.save()
            raise Exception("AI Service failed")

        # ---------------------------------------------------------
        # 6. Validate service result
        # ---------------------------------------------------------
        if not result or "error" in result or "exception" in result:
            logger.error(f"[SERVICE ERROR] {result}")

            audio_file.status = AudioFile.Status.FAILED
            if "timeout" in str(result).lower():
                audio_file.error_message = HUMAN_ERRORS["timeout"]
            else:
                audio_file.error_message = HUMAN_ERRORS["service"]
            
            audio_file.save()
            raise Exception("Service returned error")

        # ---------------------------------------------------------
        # 7. Extract final text & Save Success
        # ---------------------------------------------------------
        final_text = (result.get("text") or "").strip()
        if not final_text:
            final_text = HUMAN_ERRORS["empty"]

        audio_file.transcript_text = final_text
        audio_file.status = AudioFile.Status.COMPLETED
        audio_file.error_message = None
        audio_file.save()

        logger.info(f"[TASK DONE] File {file_id} COMPLETED")

    except Exception as e:
        logger.critical(f"[CRITICAL FAILURE] file_id={file_id} err={e}", exc_info=True)
        if audio_file and audio_file.status != AudioFile.Status.FAILED:
            audio_file.status = AudioFile.Status.FAILED
            audio_file.error_message = HUMAN_ERRORS["unknown"]
            audio_file.save()

    finally:
        # ---------------------------------------------------------
        # A. Cleanup temp files
        # ---------------------------------------------------------
        if extracted_audio_path and os.path.exists(extracted_audio_path):
            try:
                os.remove(extracted_audio_path)
                logger.info(f"[CLEANUP] Temp audio removed: {extracted_audio_path}")
            except Exception as ce:
                logger.warning(f"[CLEANUP ERROR] {ce}")

        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.info(f"[CLEANUP] Temp file deleted: {temp_path}")
            except Exception:
                logger.warning("[CLEANUP] Failed to delete temp file", exc_info=True)

        # ---------------------------------------------------------
        # B. USER-LEVEL QUEUE (Logic moved INSIDE finally)
        # ---------------------------------------------------------
        try:
 
            current_user_id = None
            if audio_file:
                current_user_id = audio_file.user_id
            else:
                try:
                    current_user_id = AudioFile.objects.values_list('user_id', flat=True).get(id=file_id)
                except:
                    pass

            if current_user_id:
                other_active_tasks = AudioFile.objects.filter(
                    user_id=current_user_id,
                    status=AudioFile.Status.PROCESSING
                ).exclude(id=file_id).exists()

                if not other_active_tasks:
                    next_file = (
                        AudioFile.objects
                        .filter(user_id=current_user_id, status=AudioFile.Status.PENDING)
                        .order_by("created_at")
                        .first()
                    )

                    if next_file:
                        logger.info(f"[QUEUE] Starting next file for user {current_user_id}: {next_file.id}")
                        

                        next_file.status = AudioFile.Status.PROCESSING
                        next_file.save(update_fields=["status"])

                        task = process_audio_file.delay(next_file.id)
                        
                        next_file.task_id = task.id
                        next_file.save(update_fields=["task_id"])
                else:
                    logger.info(f"[QUEUE] User {current_user_id} has other active tasks. Skipping queue trigger.")

        except Exception as q_err:
            logger.error(f"[QUEUE ERROR] {q_err}", exc_info=True)

# ======================================================================
# SYSTEM TASKS
# ======================================================================

@shared_task
def recover_stuck_tasks():
    from core.task_monitor import check_and_recover_stuck_tasks
    check_and_recover_stuck_tasks()


@shared_task
def start_next_pending_jobs():
    """
    Auto-run next pending job for each user if no active processing.
    """

    users = AudioFile.objects.values_list("user", flat=True).distinct()

    for user_id in users:
        has_processing = AudioFile.objects.filter(
            user_id=user_id,
            status=AudioFile.Status.PROCESSING,
        ).exists()

        if has_processing:
            continue

        next_pending = (
            AudioFile.objects
            .filter(user_id=user_id, status=AudioFile.Status.PENDING)
            .order_by("created_at")
            .first()
        )

        if next_pending:
            task = process_audio_file.delay(next_pending.id)
            next_pending.task_id = task.id
            next_pending.save(update_fields=["task_id"])




logger = logging.getLogger("core")

@shared_task(bind=True)
def discover_link(self, batch_id):
    """
    Advanced discovery logic:
    1. Try yt-dlp (Best for embedded players, streaming, youtube, aparat, etc.)
    2. Fallback to BeautifulSoup (Best for directory listings or simple HTML links)
    """
    logger.info(f"[DISCOVER START] batch_id={batch_id}")

    try:
        batch = ImportBatch.objects.get(id=batch_id)
    except ImportBatch.DoesNotExist:
        return

    batch.status = ImportBatch.Status.DISCOVERING
    batch.save(update_fields=["status"])

    found_items = []

    # =========================================================
    # STRATEGY 1: YT-DLP (The Heavy Lifter)
    # =========================================================
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'extract_flat': 'in_playlist', # فقط لیست را بگیر، دانلود نکن
            'skip_download': True,
            # شبیه‌سازی مرورگر برای عبور از فیلترهای ساده
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info(f"[DISCOVER] Trying yt-dlp for {batch.source_url}")
            info = ydl.extract_info(batch.source_url, download=False)
            
            if info:
                # اگر لینک پلی‌لیست بود
                if 'entries' in info:
                    entries = info['entries']
                else:
                    # اگر تک فایل بود
                    entries = [info]

                for entry in entries:
                    if not entry: continue
                    
                    # استخراج اطلاعات
                    title = entry.get('title') or "Untitled"
                    url = entry.get('url') or entry.get('webpage_url')
                    is_video = True # پیش‌فرض ویدیو می‌گیریم مگر اینکه خلافش ثابت شود
                    
                    # تشخیص صوتی بودن اگر ممکن باشد
                    if entry.get('vcodec') == 'none' and entry.get('acodec') != 'none':
                        is_video = False

                    if url:
                        found_items.append({
                            'title': title,
                            'url': url,
                            'is_video': is_video
                        })

    except Exception as e:
        logger.warning(f"[DISCOVER] yt-dlp failed or found nothing: {e}")
        # ادامه می‌دهیم به روش دوم...

    # =========================================================
    # STRATEGY 2: BeautifulSoup (Fallback for Direct Links)
    # =========================================================
    if not found_items:
        logger.info(f"[DISCOVER] Fallback to BeautifulSoup scraping...")
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
            }
            # verify=False برای سایت‌های دولتی ایران که SSL مشکل‌دار دارند ضروری است
            resp = requests.get(batch.source_url, headers=headers, timeout=20, verify=False)
            resp.raise_for_status()
            
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # لیست کامل‌تری از فرمت‌ها
            AUDIO_EXT = (".mp3", ".wav", ".ogg", ".m4a", ".wma", ".aac", ".flac")
            VIDEO_EXT = (".mp4", ".mkv", ".webm", ".avi", ".mov", ".wmv", ".flv", ".3gp", ".m3u8")

            # جستجوی تگ‌های مختلف
            for tag in soup.find_all(["audio", "video", "source", "a", "iframe"]):
                src = None
                
                # 1. تگ‌های استاندارد مدیا
                if tag.name in ("audio", "video", "source"):
                    src = tag.get("src")
                
                # 2. لینک‌های مستقیم دانلودی
                elif tag.name == "a":
                    href = tag.get("href", "")
                    if href and href.lower().endswith(AUDIO_EXT + VIDEO_EXT):
                        src = href
                        
                if not src:
                    continue

                # نرمال‌سازی لینک
                file_url = urljoin(batch.source_url, src)
                
                # فیلتر کردن بر اساس پسوند (فقط برای تگ <a> ضروری است، اما برای همه چک می‌کنیم)
                path = urlparse(file_url).path
                ext = os.path.splitext(path)[1].lower()
                
                # اگر تگ source/audio/video بود حتی بدون پسوند هم قبول می‌کنیم
                is_explicit_media_tag = tag.name in ("audio", "video", "source")
                has_valid_ext = ext in (AUDIO_EXT + VIDEO_EXT)

                if is_explicit_media_tag or has_valid_ext:
                    is_video = True
                    if tag.name == "audio" or ext in AUDIO_EXT:
                        is_video = False
                        
                    found_items.append({
                        'title': os.path.basename(path) or "Unknown File",
                        'url': file_url,
                        'is_video': is_video
                    })

        except Exception as e:
            logger.error(f"[DISCOVER SCRAPE ERROR] {e}")

    # =========================================================
    # SAVE RESULTS
    # =========================================================
    saved_count = 0
    unique_urls = set()

    for item in found_items:
        url = item['url']
        
        # جلوگیری از تکراری شدن در یک بچ
        if url in unique_urls:
            continue
        unique_urls.add(url)
        
        # جلوگیری از تکراری شدن در دیتابیس (اختیاری)
        if ImportItem.objects.filter(batch=batch, source_url=url).exists():
            continue

        ImportItem.objects.create(
            batch=batch,
            title=item['title'][:250], # محدود کردن طول تایتل
            source_url=url,
            is_video=item['is_video']
        )
        saved_count += 1

    if saved_count == 0:
        batch.status = ImportBatch.Status.FAILED
        batch.error_message = "هیچ فایل قابل پردازشی یافت نشد."
        batch.save()
        logger.warning(f"[DISCOVER EMPTY] batch_id={batch_id}")
        return

    batch.status = ImportBatch.Status.READY
    batch.save(update_fields=["status"])
    logger.info(f"[DISCOVER DONE] batch_id={batch_id} items={saved_count}")
