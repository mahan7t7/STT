# core/tasks.py

import logging
from celery import shared_task
from .models import AudioFile
from .services import EbooService, ScribeService, ViraService

logger = logging.getLogger('core')


@shared_task(bind=True)
def process_audio_file(self, file_id):
    """
    Celery task to process an uploaded audio file.

    Works with 3 models:
    - eboo
    - scribe
    - vira

    Keeps:
    - User-level queue
    - Cancellation support
    - Error handling
    """

    logger.info(f"[TASK START] file_id={file_id}")

    try:
        # ---------------------------------------------------------
        # Load DB record
        # ---------------------------------------------------------
        try:
            audio_file = AudioFile.objects.get(id=file_id)
        except AudioFile.DoesNotExist:
            logger.error(f"[ERROR] AudioFile {file_id} not found in DB.")
            return

        # ---------------------------------------------------------
        # Track Celery task ID (for revoke)
        # ---------------------------------------------------------
        audio_file.task_id = self.request.id
        audio_file.save()

        # ---------------------------------------------------------
        # Set status → PROCESSING
        # ---------------------------------------------------------
        audio_file.status = AudioFile.Status.PROCESSING
        audio_file.save()
        logger.info(f"[STATUS] File {file_id} → PROCESSING")

        # ---------------------------------------------------------
        # Select service based on model_name
        # ---------------------------------------------------------
        model = audio_file.model_name or "eboo"
        file_path = audio_file.audio_file.path
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
            audio_file.error_message = "خطا در ارتباط با سرویس پردازش صوت."
            audio_file.save()
            return

        # ---------------------------------------------------------
        # Validate service result
        # ---------------------------------------------------------
        if (
            not result
            or "error" in result
            or "exception" in result
        ):
            logger.error(f"[SERVICE ERROR] {result}")
            audio_file.status = AudioFile.Status.FAILED
            audio_file.error_message = result.get("error") or result.get("exception")
            audio_file.save()
            return

        # ---------------------------------------------------------
        # Extract final text
        # ---------------------------------------------------------
        final_text = result.get("text", "").strip()
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
        try:
            f = AudioFile.objects.get(id=file_id)
            f.status = AudioFile.Status.FAILED
            f.error_message = "خطای فنی غیرمنتظره در سرور."
            f.save()
        except Exception:
            logger.critical("Database unreachable during failure recovery.")

    # ======================================================================
    # USER-LEVEL QUEUE
    # Auto-start next pending file for the same user
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
