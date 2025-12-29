# core/views.py

import os
import io
import textwrap

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.http import (
    HttpResponse,
    JsonResponse,
    HttpResponseBadRequest
)
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.conf import settings

from .forms import AudioUploadForm, SignUpForm
from .models import AudioFile
from .tasks import process_audio_file

# Word export
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

# PDF export
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import arabic_reshaper
from bidi.algorithm import get_display

from celery import current_app


# ---------------------------------------------------------
# Utility Helpers
# ---------------------------------------------------------

def clean_text_for_export(text):
    """Replaces emojis with export-safe text."""
    if not text:
        return ""
    repl = {
        '🕒': ' [زمان]: ',
        '🎵': ' [موسیقی]: ',
        '🆔': ' [گوینده]: ',
        '✔': ' [تیک] ',
        '⚠': ' [هشدار] ',
    }
    for k, v in repl.items():
        text = text.replace(k, v)
    return text


def get_safe_filename(audio_file, ext):
    """Generates a safe, user-friendly filename."""
    if audio_file.audio_file:
        try:
            original = os.path.basename(audio_file.audio_file.name)
            name = os.path.splitext(original)[0]
            clean = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
            return f"{clean}.{ext}"
        except:
            pass
    return f"transcript_{audio_file.id}.{ext}"


# ---------------------------------------------------------
# Landing + Authentication
# ---------------------------------------------------------

def landing(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "core/landing.html")



def signup(request):
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("dashboard")  # ✅ مهم
    else:
        form = SignUpForm()

    return render(request, "registration/signup.html", {"form": form})


# ---------------------------------------------------------
# Dashboard (GET)
# Table updates via AJAX (polling)
# ---------------------------------------------------------

@login_required
def dashboard(request):
    """Main dashboard page."""
    files = AudioFile.objects.filter(user=request.user).order_by("-created_at")
    paginator = Paginator(files, 10)
    page = request.GET.get("page")
    page_obj = paginator.get_page(page)

    return render(request, "core/dashboard.html", {"files": page_obj})


# ---------------------------------------------------------
# Upload (AJAX)
# ---------------------------------------------------------

@login_required
def upload_file(request):
    """AJAX Upload — ensures each user can process only ONE file at a time."""
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid request")

    form = AudioUploadForm(request.POST, request.FILES, user=request.user)

    if not form.is_valid():
        return JsonResponse({
            "success": False,
            "errors": form.errors
        }, status=400)

    # Save file (status default = uploading)
    audio = form.save()

    # --------- IMPORTANT LOGIC ----------
    # Does this user already have an active job?
    user_has_active_job = AudioFile.objects.filter(
        user=request.user,
        status__in=[AudioFile.Status.PENDING, AudioFile.Status.PROCESSING]
    ).exists()

    if user_has_active_job:
        # Another job is running → this file must wait
        audio.status = AudioFile.Status.PENDING
        audio.save()

    else:
        # User is free → start processing immediately
        audio.status = AudioFile.Status.PENDING
        audio.save()
        result = process_audio_file.delay(audio.id)

        # save Celery task_id to enable revoke on delete
        audio.task_id = result.id
        audio.save()

    return JsonResponse({
        "success": True,
        "file_id": audio.id
    })

# ---------------------------------------------------------
# AJAX — File list refresh for polling
# ---------------------------------------------------------

@login_required
def get_files(request):
    """Returns updated table HTML for polling."""
    files = AudioFile.objects.filter(user=request.user).order_by("-created_at")
    paginator = Paginator(files, 10)
    page = request.GET.get("page")
    page_obj = paginator.get_page(page)

    html = render_to_string(
        "partials/file_table_container.html",
        {"files": page_obj},
        request=request
    )
    return HttpResponse(html)


@login_required
def update_row(request, file_id):
    """Returns HTML for a single table row."""
    file = get_object_or_404(AudioFile, id=file_id, user=request.user)
    html = render_to_string("partials/row.html", {"file": file}, request=request)
    return HttpResponse(html)


# ---------------------------------------------------------
# Delete File (AJAX + JSON response)
# With REAL Celery terminate
# ---------------------------------------------------------

@login_required
def delete_file(request, pk):
    """
    AJAX-only deletion endpoint.
    - Accepts DELETE request.
    - Kills Celery task if still running.
    - Removes DB entry.
    - Returns JSON.
    """
    if request.method != "DELETE":
        return HttpResponseBadRequest("Invalid request")

    obj = get_object_or_404(AudioFile, pk=pk, user=request.user)

    # Kill Celery task if in progress
    # if obj.task_id:
    #     try:
    #         app = current_app
    #         app.control.revoke(obj.task_id, terminate=True, signal='SIGKILL')
    #     except Exception as e:
    #         print("Celery revoke error:", e)

    obj.delete()

    return JsonResponse({"success": True})


# ---------------------------------------------------------
# Downloads
# ---------------------------------------------------------

@login_required
def download_txt(request, file_id):
    """Exports transcript as TXT."""
    audio_file = get_object_or_404(AudioFile, id=file_id, user=request.user)
    raw = audio_file.transcript_text or "متنی موجود نیست."
    txt = clean_text_for_export(raw)

    content = f"عنوان: {audio_file.title}\n------------------\n{txt}"

    response = HttpResponse(content, content_type="text/plain; charset=utf-8")
    filename = get_safe_filename(audio_file, "txt")
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{filename}"
    return response


@login_required
def download_word(request, file_id):
    """Exports transcript as a Word DOCX file."""
    audio_file = get_object_or_404(AudioFile, id=file_id, user=request.user)

    doc = Document()
    title_p = doc.add_heading(audio_file.title or "متن استخراج شده", 0)
    title_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    raw = audio_file.transcript_text or "متنی موجود نیست."
    clean = clean_text_for_export(raw)

    for line in clean.split("\n"):
        if line.strip():
            p = doc.add_paragraph(line)
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            p.paragraph_format.bidi = True
            if p.runs:
                r = p.runs[0]
                r.font.name = "Arial"
                r.font.size = Pt(12)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    response = HttpResponse(
        buf,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    filename = get_safe_filename(audio_file, "docx")
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{filename}"
    return response


@login_required
def download_pdf(request, file_id):
    """Exports transcript as PDF."""
    audio_file = get_object_or_404(AudioFile, id=file_id, user=request.user)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin_x, margin_y = 50, 50

    font_name = "Helvetica"
    try:
        path = os.path.join(settings.BASE_DIR, "core", "static", "fonts", "Vazir.ttf")
        pdfmetrics.registerFont(TTFont("Vazir", path))
        font_name = "Vazir"
    except Exception as e:
        print("Font error:", e)

    c.setFont(font_name, 12)

    raw = audio_file.transcript_text or "متنی موجود نیست."
    clean = clean_text_for_export(raw)

    y = height - margin_y
    line_h = 20

    for paragraph in clean.split("\n"):
        if not paragraph.strip():
            y -= line_h
            continue

        lines = textwrap.wrap(paragraph, width=90)

        for l in lines:
            if font_name == "Vazir":
                reshaped = arabic_reshaper.reshape(l)
                bidi = get_display(reshaped)
            else:
                bidi = l

            c.drawRightString(width - margin_x, y, bidi)
            y -= line_h

            if y < margin_y:
                c.showPage()
                c.setFont(font_name, 12)
                y = height - margin_y

    c.showPage()
    c.save()

    buf.seek(0)
    response = HttpResponse(buf, content_type="application/pdf")
    filename = get_safe_filename(audio_file, "pdf")
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{filename}"
    return response
