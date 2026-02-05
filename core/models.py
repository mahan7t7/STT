from django.db import models
from django.contrib.auth.models import User
import os

class STTModelChoices(models.TextChoices):
    EBOO = 'eboo', 'Eboo'
    VIRA = 'vira', 'Vira'
    SCRIBE = 'scribe', 'Scribe'




class ImportBatch(models.Model):
    """
    Represents a single import-by-link request.
    One link → multiple discovered media items.
    """

    class Status(models.TextChoices):
        CREATED = "created", "ایجاد شده"
        DISCOVERING = "discovering", "در حال بررسی لینک"
        READY = "ready", "آماده انتخاب"
        FAILED = "failed", "خطا"

    model_name = models.CharField(
        max_length=20,
        choices=STTModelChoices.choices,
        default=STTModelChoices.EBOO,
        verbose_name="مدل پردازش"
    )
    
    
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="import_batches",
        verbose_name="کاربر"
    )

    source_url = models.TextField(
        verbose_name="لینک منبع"
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CREATED,
        verbose_name="وضعیت"
    )

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

    def __str__(self):
        return f"Import #{self.id} - {self.source_url}"

class AudioFile(models.Model):
    """
    Represents a single audio/video item selected for transcription.
    Can originate from direct upload or from an ImportBatch.
    """

    # ==============================
    # Status choices
    # ==============================
    class Status(models.TextChoices):
        UPLOADING = 'uploading', 'در حال آپلود'
        PENDING = 'pending', 'در صف پردازش'
        PROCESSING = 'processing', 'در حال پردازش'
        COMPLETED = 'completed', 'تکمیل شده'
        FAILED = 'failed', 'خطا'

    # ==============================
    # Speech-to-text model choices
    # ==============================
    class ModelChoices(models.TextChoices):
        EBOO = 'eboo', 'Eboo'
        VIRA = 'vira', 'Vira'
        SCRIBE = 'scribe', 'Scribe'

    # ==============================
    # Owner
    # ==============================
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="کاربر"
    )

    # ==============================
    # Relation to import batch (optional)
    # ==============================
    import_batch = models.ForeignKey(
        "ImportBatch",
        on_delete=models.CASCADE,
        related_name="files",
        blank=True,
        null=True,
        verbose_name="ورودی لینک"
    )

    # ==============================
    # Metadata
    # ==============================
    title = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="عنوان"
    )

    # ==============================
    # Input source
    # ==============================
    audio_file = models.FileField(
        upload_to='uploads/audio/',
        blank=True,
        null=True,
        verbose_name="فایل صوتی"
    )

    source_url = models.TextField(
        blank=True,
        null=True,
        verbose_name="لینک فایل"
    )

    is_video = models.BooleanField(
        default=False,
        verbose_name="فایل ویدیویی است؟"
    )

    # ==============================
    # Processing config
    # ==============================
    model_name = models.CharField(
        max_length=20,
        choices=STTModelChoices.choices,
        default=STTModelChoices.EBOO,
        verbose_name="مدل پردازش"
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UPLOADING,
        verbose_name="وضعیت"
    )

    # ==============================
    # Result & error
    # ==============================
    transcript_text = models.TextField(
        blank=True,
        null=True,
        verbose_name="متن استخراج شده"
    )
    
    summary_text = models.TextField(
        blank=True,
        null=True,
        verbose_name="خلاصه متن"
    )

    show_summary = models.BooleanField(
        default=True,
        verbose_name="نمایش خلاصه به جای متن کامل"
    )

    error_message = models.TextField(
        blank=True,
        null=True,
        verbose_name="پیام خطا"
    )

    # ==============================
    # System
    # ==============================
    task_id = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "فایل پردازشی"
        verbose_name_plural = "فایل‌های پردازشی"

    def __str__(self):
        return self.title or f"File #{self.id}"

    @property
    def filename(self):
        if self.audio_file:
            return os.path.basename(self.audio_file.name)
        return None

    @property
    def is_from_link(self):
        return bool(self.source_url)
    
    
    
class ImportItem(models.Model):
    """
    Represents a single discovered media file in an ImportBatch.
    User will select which ones to convert.
    """

    batch = models.ForeignKey(
        ImportBatch,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="دسته ایمپورت"
    )

    title = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="عنوان"
    )

    source_url = models.TextField(
        verbose_name="لینک فایل"
    )

    is_video = models.BooleanField(
        default=False,
        verbose_name="ویدیویی است؟"
    )

    duration = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name="مدت (ثانیه)"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title or self.source_url
    