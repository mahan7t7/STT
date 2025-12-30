# core/tasks.py

import logging
import os
from celery import shared_task
from .models import AudioFile
from .services import EbooService, ScribeService, ViraService, MediaService

HUMAN_ERRORS = {
    "video": "خطا در استخراج صدا از فایل ویدیویی.",
    "service": "خطا در ارتباط با سرویس پردازش",
    "timeout": "پردازش فایل بیش از حد طول کشید",
    "empty": "متنی از فایل استخراج نشد",
    "unknown": "خطای نامشخص در پردازش فایل",
}



logger = logging.getLogger('core')


@shared_task(bind=True)
def process_audio_file(self, file_id):
    """
    Celery task to process an uploaded audio/video file.

    Supports:
    - Audio files
    - Video → extract audio → STT

    Features:
    - User-level queue
    - Human-readable errors
    - Safe error handling
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
        # Track Celery task ID
        # ---------------------------------------------------------
        audio_file.task_id = self.request.id
        audio_file.status = AudioFile.Status.PROCESSING
        audio_file.save()
        logger.info(f"[STATUS] File {file_id} → PROCESSING")

        # ---------------------------------------------------------
        # Resolve file path (video → audio if needed)
        # ---------------------------------------------------------
        file_path = audio_file.audio_file.path

        if audio_file.is_video:
            logger.info(f"[VIDEO] Extracting audio from video for file {file_id}")
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
        model = audio_file.model_name or "eboo"
        logger.debug(f"[AI SERVICE] model={model} file={file_path}")

        try:
            if model == "eboo":
                result = EbooService.process(file_path)

            elif model == "scribe":
                result = ScribeService.process(file_path)

            elif model == "vira":
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
        # Validate result
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
            final_text = "متنی استخراج نشد."

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
            exc_info=True
        )
        if audio_file:
            audio_file.status = AudioFile.Status.FAILED
            audio_file.error_message = HUMAN_ERRORS["unknown"]
            audio_file.save()

    finally:
        # ---------------------------------------------------------
        # Cleanup extracted temp audio
        # ---------------------------------------------------------
        if extracted_audio_path and os.path.exists(extracted_audio_path):
            try:
                os.remove(extracted_audio_path)
                logger.info(f"[CLEANUP] Temp audio removed: {extracted_audio_path}")
            except Exception as ce:
                logger.warning(f"[CLEANUP ERROR] {ce}")

    # ======================================================================
    # USER-LEVEL QUEUE
    # ======================================================================
    try:
        next_file = AudioFile.objects.filter(
            user=audio_file.user,
            status=AudioFile.Status.PENDING
        ).order_by("created_at").first()

        if next_file:
            logger.info(
                f"[QUEUE] Starting next file for user {audio_file.user.id}: {next_file.id}"
            )
            task = process_audio_file.delay(next_file.id)
            next_file.task_id = task.id
            next_file.save()

    except Exception as q_err:
        logger.error(f"[QUEUE ERROR] {q_err}", exc_info=True)



# ======================================================================
#  SYSTEM TASKS
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
    from core.models import AudioFile
    from core.tasks import process_audio_file

    users = AudioFile.objects.values_list("user", flat=True).distinct()

    for user_id in users:
        # If this user has an active job, ignore
        has_processing = AudioFile.objects.filter(
            user_id=user_id,
            status=AudioFile.Status.PROCESSING
        ).exists()

        if has_processing:
            continue

        # Otherwise pull next pending
        next_pending = AudioFile.objects.filter(
            user_id=user_id,
            status=AudioFile.Status.PENDING
        ).order_by("created_at").first()

        if next_pending:
            next_pending.status = AudioFile.Status.PROCESSING
            next_pending.save()

            task = process_audio_file.delay(next_pending.id)
            next_pending.task_id = task.id
            next_pending.save()
