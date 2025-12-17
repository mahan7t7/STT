# core/task_monitor.py

from celery.result import AsyncResult
from .models import AudioFile

def check_and_recover_stuck_tasks():
    """
    This function detects stuck tasks that remained in 'processing'
    after Celery restart or crash. It recovers them back to 'pending'.
    """

    stuck = AudioFile.objects.filter(status='processing', task_id__isnull=False)

    for audio in stuck:
        result = AsyncResult(audio.task_id)

        # If task is missing, revoked, or not found → recover
        if result.state in ["PENDING", "REVOKED", "FAILURE"]:
            audio.status = "pending"
            audio.save()
