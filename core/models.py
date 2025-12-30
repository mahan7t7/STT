from django.db import models
from django.contrib.auth.models import User
import os


class AudioFile(models.Model):
    """
    Audio file model storing upload info, processing status,
    transcript results, and Celery task tracking for killing tasks.
    """

    class Status(models.TextChoices):
        UPLOADING = 'uploading', 'در حال آپلود'
        PENDING = 'pending', 'در صف پردازش'
        PROCESSING = 'processing', 'در حال پردازش'
        COMPLETED = 'completed', 'تکمیل شده'
        FAILED = 'failed', 'خطا'

    # -------- NEW FIELD (model selection) --------
    class ModelChoices(models.TextChoices):
        EBOO = 'eboo', 'Eboo'
        VIRA = 'vira', 'Vira'
        SCRIBE = 'scribe', 'Scribe'

    model_name = models.CharField(
        max_length=20,
        choices=ModelChoices.choices,
        default=ModelChoices.EBOO,
        verbose_name="مدل پردازش"
    )
    # ---------------------------------------------

    # Owner user
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="کاربر"
    )

    # Optional title
    title = models.CharField(
        max_length=255,
        verbose_name="عنوان",
        blank=True,
        null=True
    )

    # Main audio file
    audio_file = models.FileField(
        upload_to='uploads/audio/',
        verbose_name="فایل صوتی"
    )
    
    is_video = models.BooleanField(
        default=False,
        verbose_name="فایل ویدیویی است؟"
    )

    # Status of processing
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UPLOADING,
        verbose_name="وضعیت"
    )

    # Final transcript text
    transcript_text = models.TextField(
        blank=True,
        null=True,
        verbose_name="متن استخراج شده"
    )

    # Error message (if any)
    error_message = models.TextField(
        blank=True,
        null=True,
        verbose_name="پیام خطا"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="تاریخ ایجاد"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="آخرین بروزرسانی"
    )

    # Celery task ID for killing the running task
    task_id = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    class Meta:
        verbose_name = "فایل صوتی"
        verbose_name_plural = "فایل‌های صوتی"
        ordering = ['-created_at']

    def __str__(self):
        return self.title or f"فایل شماره {self.id}"

    @property
    def filename(self):
        """Returns the file's base filename."""
        return os.path.basename(self.audio_file.name)
