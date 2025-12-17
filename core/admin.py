from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import AudioFile

class AudioFileInline(admin.TabularInline):
    """
    این کلاس باعث می‌شود فایل‌های صوتی به صورت یک لیست
    در پایین صفحه ویرایش هر کاربر نمایش داده شوند.
    """
    model = AudioFile
    extra = 0  
    fields = ('title', 'status', 'created_at') 
    readonly_fields = ('created_at',) 


class UserAdmin(BaseUserAdmin):
    inlines = (AudioFileInline,)  
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'get_files_count')

    def get_files_count(self, obj):
        return obj.audiofile_set.count()
    get_files_count.short_description = 'تعداد فایل‌ها'


admin.site.unregister(User)
admin.site.register(User, UserAdmin)




@admin.register(AudioFile)
class AudioFileAdmin(admin.ModelAdmin):

    list_display = ('title', 'user', 'status', 'get_created_at_jalali')
    
    list_filter = ('status', 'created_at', 'user') 
    search_fields = ('title', 'transcript_text', 'user__username') 
    readonly_fields = ('created_at',)

    def get_created_at_jalali(self, obj):
        from .templatetags.jalali_tags import to_jalali
        return to_jalali(obj.created_at)
    
    get_created_at_jalali.short_description = 'تاریخ ایجاد (شمسی)'
