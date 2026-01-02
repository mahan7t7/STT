# core/tasks.py

import logging
import os
from celery import shared_task
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from core.services import download_temp_file


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


@shared_task(bind=True)
def process_audio_file(self, file_id):
    """
    Celery task to process a single AudioFile.

    Supports:
    - audio upload
    - video upload (audio extraction)
    - user-level queue
    """

    logger.info(f"[TASK START] file_id={file_id}")

    audio_file = None
    extracted_audio_path = None

    try:
        # ---------------------------------------------------------
        # Load DB record
        # ---------------------------------------------------------
        try:
            audio_file = AudioFile.objects.get(id=file_id)
        except AudioFile.DoesNotExist:
            logger.error(f"[ERROR] AudioFile {file_id} not found.")
            return

        # ---------------------------------------------------------
        # Track task + set PROCESSING
        # ---------------------------------------------------------
        audio_file.task_id = self.request.id
        audio_file.status = AudioFile.Status.PROCESSING
        audio_file.save(update_fields=["task_id", "status"])

        logger.info(f"[STATUS] File {file_id} → PROCESSING")

        # -------------------------------
        # Resolve file_path
        # -------------------------------
        temp_path = None

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
                return

        else:
            audio_file.status = AudioFile.Status.FAILED
            audio_file.error_message = "هیچ منبع فایلی یافت نشد."
            audio_file.save()
            return

        # ---------------------------------------------------------
        # Video → extract audio
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
                return

        # ---------------------------------------------------------
        # Select AI service
        # ---------------------------------------------------------
        model = audio_file.model_name or AudioFile.ModelChoices.EBOO
        logger.debug(f"[AI SERVICE] model={model} file={file_path}")

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
            return

        # ---------------------------------------------------------
        # Validate service result
        # ---------------------------------------------------------
        if not result or "error" in result or "exception" in result:
            logger.error(f"[SERVICE ERROR] {result}")

            audio_file.status = AudioFile.Status.FAILED

            if "timeout" in str(result).lower():
                audio_file.error_message = HUMAN_ERRORS["timeout"]
            else:
                audio_file.error_message = HUMAN_ERRORS["service"]

            audio_file.save()
            return

        # ---------------------------------------------------------
        # Extract final text
        # ---------------------------------------------------------
        final_text = (result.get("text") or "").strip()
        if not final_text:
            final_text = HUMAN_ERRORS["empty"]

        # ---------------------------------------------------------
        # Save success
        # ---------------------------------------------------------
        audio_file.transcript_text = final_text
        audio_file.status = AudioFile.Status.COMPLETED
        audio_file.error_message = None
        audio_file.save()

        logger.info(f"[TASK DONE] File {file_id} COMPLETED")

    except Exception as e:
        logger.critical(
            f"[CRITICAL FAILURE] file_id={file_id} err={e}",
            exc_info=True,
        )
        if audio_file:
            audio_file.status = AudioFile.Status.FAILED
            audio_file.error_message = HUMAN_ERRORS["unknown"]
            audio_file.save()

    finally:
        # ---------------------------------------------------------
        # Cleanup temp extracted audio
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

    # ======================================================================
    # USER-LEVEL QUEUE
    # ======================================================================
    try:
        if not audio_file:
            return

        next_file = (
            AudioFile.objects
            .filter(user=audio_file.user, status=AudioFile.Status.PENDING)
            .order_by("created_at")
            .first()
        )

        if next_file:
            logger.info(
                f"[QUEUE] Starting next file for user {audio_file.user_id}: {next_file.id}"
            )
            task = process_audio_file.delay(next_file.id)
            next_file.task_id = task.id
            next_file.save(update_fields=["task_id"])

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




@shared_task(bind=True)
def discover_link(self, batch_id):
    """
    Discover audio/video files from a given ImportBatch.source_url.
    Creates ImportItem records for preview.
    """

    logger.info(f"[DISCOVER START] batch_id={batch_id}")

    try:
        batch = ImportBatch.objects.get(id=batch_id)
    except ImportBatch.DoesNotExist:
        logger.error(f"[DISCOVER ERROR] Batch {batch_id} not found")
        return

    batch.status = ImportBatch.Status.DISCOVERING
    batch.save(update_fields=["status"])

    try:
        resp = requests.get(batch.source_url, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"[DISCOVER FETCH ERROR] {e}")
        batch.status = ImportBatch.Status.FAILED
        batch.error_message = "دریافت لینک امکان‌پذیر نبود."
        batch.save()
        return

    soup = BeautifulSoup(resp.text, "html.parser")

    found = 0
    AUDIO_EXT = (".mp3", ".wav", ".ogg", ".m4a")
    VIDEO_EXT = (".mp4", ".mkv", ".webm", ".avi")

    for tag in soup.find_all(["audio", "video", "a"]):
        src = None

        if tag.name in ("audio", "video"):
            src = tag.get("src")
        elif tag.name == "a":
            href = tag.get("href", "")
            if href.lower().endswith(AUDIO_EXT + VIDEO_EXT):
                src = href

        if not src:
            continue

        file_url = urljoin(batch.source_url, src)
        ext = os.path.splitext(urlparse(file_url).path)[1].lower()

        is_video = ext in VIDEO_EXT

        ImportItem.objects.create(
            batch=batch,
            title=os.path.basename(file_url),
            source_url=file_url,
            is_video=is_video
        )

        found += 1

    if found == 0:
        batch.status = ImportBatch.Status.FAILED
        batch.error_message = "هیچ فایل صوتی یا ویدیویی در لینک یافت نشد."
        batch.save()
        logger.warning(f"[DISCOVER EMPTY] batch_id={batch_id}")
        return

    batch.status = ImportBatch.Status.READY
    batch.save(update_fields=["status"])

    logger.info(f"[DISCOVER DONE] batch_id={batch_id} items={found}")
