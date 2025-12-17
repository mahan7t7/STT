# core/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import AudioFile


class AudioUploadForm(forms.ModelForm):
    
    def __init__(self, *args, **kwargs):
        """
        دریافت و ذخیره user از kwargs برای اتصال فایل به کاربر لاگین‌شده
        """
        self.user = kwargs.pop('user', None)
        super(AudioUploadForm, self).__init__(*args, **kwargs)

    class Meta:
        model = AudioFile


        fields = ['title', 'audio_file', 'model_name']

        labels = {
            'title': 'عنوان فایل',
            'audio_file': 'انتخاب فایل صوتی',
            'model_name': 'انتخاب مدل پردازش',
        }

        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'یک عنوان برای فایل بنویسید...'
            }),
            'audio_file': forms.FileInput(attrs={
                'class': 'form-control',
                'id': 'audioFileInput'
            }),
            'model_name': forms.Select(attrs={
                'class': 'form-control',
            }),
        }

    def save(self, commit=True):
        """
        قبل از ذخیره، user را روی instance تنظیم می‌کنیم
        """
        instance = super(AudioUploadForm, self).save(commit=False)

        if self.user:
            instance.user = self.user

        if commit:
            instance.save()

        return instance



class SignUpForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['username', 'email']
        labels = {
            'username': 'نام کاربری',
            'email': 'آدرس ایمیل (اختیاری)',
        }
        help_texts = {
            'username': 'نام کاربری باید انگلیسی باشد.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name in self.fields:
            self.fields[field_name].widget.attrs.update({'class': 'form-control'})

            if field_name == 'username':
                self.fields[field_name].widget.attrs['placeholder'] = 'مثلاً: ali_reza'
