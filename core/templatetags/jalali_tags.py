from django import template
from django.utils import timezone  
import jdatetime
import os 
import re

register = template.Library()

@register.filter
def to_jalali(value):
    """
    تبدیل تاریخ میلادی به شمسی با لحاظ کردن اختلاف ساعت
    """
    if value is None:
        return ""
    

    try:
        local_value = timezone.localtime(value)
    except Exception:

        local_value = value


    jalali_date = jdatetime.datetime.fromgregorian(datetime=local_value)
    

    return jalali_date.strftime("%H:%M - %Y/%m/%d")


@register.filter
def filename(value):
    """
    مسیر کامل فایل را می‌گیرد و فقط نام فایل را برمی‌گرداند.
    مثال: uploads/audio/test.mp3 -> test.mp3
    """
    return os.path.basename(str(value))



@register.filter
def clean_filename(file_path):
    """
    Removes random suffixes like _12fJDSa before extension (e.g. audio_12fJDSa.mp3 → audio.mp3)
    """
    filename = os.path.basename(file_path)
    name, ext = os.path.splitext(filename)
    clean_name = re.sub(r'_[a-zA-Z0-9]+$', '', name)
    return f"{clean_name}{ext}"
