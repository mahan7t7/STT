# core/services.py
import json
import time
import requests
import os
import subprocess
import uuid
import tempfile
import shutil
from django.conf import settings
from django.contrib.sites.models import Site
from urllib.parse import urlparse



# ============================================================
#   EBOO SERVICE 
# ============================================================

import os
import time
import requests
from django.conf import settings

# core/services.py
import json
import time
import requests
import os
from django.conf import settings


def get_audio_duration(path: str) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except:
        return 0.0


class EbooService:
    BASE_URL = "https://www.eboo.ir/api/ocr/getway"

    @staticmethod
    def process(file_path: str):
        token = getattr(settings, "EBOO_TOKEN", None)
        if not token:
            return {"error": "EBOO_TOKEN missing in settings"}

        if not os.path.exists(file_path):
            return {"error": "File not found"}

        with open(file_path, "rb") as f:
            files = {"filehandle": f}
            data = {
                "token": token,
                "command": "addfile"
            }
            r = requests.post(EbooService.BASE_URL, data=data, files=files)

        if r.status_code != 200:
            return {"error": f"Eboo addfile failed: {r.text}"}

        res = r.json()
        file_token = res.get("FileToken") or res.get("filetoken")
        if not file_token:
            return {"error": "Eboo addfile: file token missing"}


        data2 = {
            "token": token,
            "command": "convert",
            "filetoken": file_token,
            "language": "fa"
        }

        r2 = requests.post(EbooService.BASE_URL, json=data2)
        if r2.status_code != 200:
            return {"error": f"Eboo convert failed: {r2.text}"}

        for _ in range(60):  
            time.sleep(2)
            check = {
                "token": token,
                "command": "checkconvert",
                "filetoken": file_token
            }
            r3 = requests.post(EbooService.BASE_URL, json=check)
            if r3.status_code != 200:
                continue

            try:
                js = r3.json()
            except Exception:
                continue

            status = js.get("Status", "")
            if status == "ConvertFinished":
                output_text = js.get("Output", "").strip()
                return {"text": output_text}

            if status in ("ConvertFailed", "Error"):
                return {"error": f"Eboo conversion failed: {js}"}

        return {"error": "Eboo polling timeout"}
    
    
# ============================================================
#   SCRIBE SERVICE 
# ============================================================    

import os
import json
import time
import requests
from django.conf import settings

class ScribeService:
    STORAGE_URL = "https://api.metisai.ir/api/v1/storage"
    GENERATE_URL = "https://api.metisai.ir/api/v2/generate"

    @classmethod
    def process(cls, file_path: str):
        token = getattr(settings, "SCRIBE_TOKEN", None)
        if not token:
            return {"error": "SCRIBE_TOKEN missing in settings"}
        
        if not os.path.exists(file_path):
            return {"error": f"File not found: {file_path}"}

        headers = {"Authorization": f"Bearer {token}"}

        try:
            with open(file_path, "rb") as f:
                files = {"files": (os.path.basename(file_path), f)}
                print(f"[SCRIBE] Uploading file: {file_path}")
                upload = requests.post(cls.STORAGE_URL, headers=headers, files=files, timeout=900)
        except Exception as e:
            return {"exception": f"Upload error: {e}"}

        if upload.status_code not in (200, 201):
            return {"error": f"Upload failed: {upload.text}"}

        up_json = upload.json()
        files_list = up_json.get("files")
        if not files_list or not isinstance(files_list, list) or not files_list[0].get("url"):
            return {"error": "No audio_url returned", "raw": up_json}
        
        audio_url = files_list[0]["url"]
        print(f"[SCRIBE] File uploaded. URL obtained.")
        
        time.sleep(2) 

        payload = {
            "model": {
                "name": "elevenlabs",
                "model": "scribe_v1"
            },
            "operation": "STT",
            "args": {
                "url": audio_url,
                "audio_url": audio_url,
                "file": audio_url,
                "audio": audio_url,
                "source": audio_url,
                "file_url": audio_url
            }
        }

        try:
            gen_resp = requests.post(cls.GENERATE_URL, headers=headers, json=payload, timeout=900)
        except Exception as e:
            return {"exception": f"Generate error: {e}"}

        if gen_resp.status_code not in (200, 201):
            return {"error": f"Generate failed: {gen_resp.text}"}

        gen_json = gen_resp.json()
        task_id = gen_json.get("id")
        if not task_id:
            return {"error": "No task ID returned", "raw": gen_json}

        print(f"[SCRIBE] Task started. ID: {task_id}")
        poll_url = f"{cls.GENERATE_URL}/{task_id}"

        for attempt in range(60): 
            try:
                poll_resp = requests.get(poll_url, headers=headers, timeout=900)
                if poll_resp.status_code == 200:
                    js = poll_resp.json()
                    status = js.get("status")
                    
                    if status == "COMPLETED":
                        gens = js.get("generations")
                        if gens and isinstance(gens, list) and len(gens) > 0:
                            first_gen = gens[0]
                            final_text = first_gen.get("content") or first_gen.get("text")
                            
                            if not final_text and first_gen.get("url"):
                                result_url = first_gen.get("url")
                                print(f"[SCRIBE] Result is a file link, downloading content from: {result_url}")
                                try:
                                    txt_resp = requests.get(result_url)
                                    txt_resp.encoding = 'utf-8' 
                                    final_text = txt_resp.text.strip().strip('"')
                                except Exception as dl_err:
                                    return {"error": f"Failed to download result text: {dl_err}"}

                            if final_text:
                                return {"text": final_text}
                            else:
                                return {"text": "Generation completed but content is empty"}
                        
                        return {"text": str(gens) if gens else "No generations found"}
                        
                    elif status == "ERROR":
                        return {"error": "SCRIBE task failed", "raw": js}
                
                time.sleep(5)
            except Exception as e:
                print(f"[SCRIBE] Polling error: {e}")
                time.sleep(5)

        return {"error": "Timeout waiting for Scribe result"}




# ============================================================
#   VIRA SERVICE 
# ============================================================

import requests
import os
from django.conf import settings

class ViraService:
    """Avanegar (Vira) speech-to-text service"""

    URL = "https://partai.gw.isahab.ir/avanegar/v2/avanegar/request"

    @staticmethod
    def process(file_path: str):
        token = getattr(settings, "VIRA_TOKEN", None)
        if not token:
            return {"error": "VIRA_TOKEN missing in settings"}

        if not os.path.exists(file_path):
            return {"error": f"File not found: {file_path}"}

        headers = {
            "gateway-token": token,
            "accept": "application/json"
        }

        filename = os.path.basename(file_path)
        mime_type = "audio/wav"
        model_type = "telephony"   

        data = {
            "model": model_type,
            "srt": "false",
            "inverseNormalizer": "false",
            "timestamp": "false",
            "spokenPunctuation": "false",
            "punctuation": "true",
            "numSpeakers": "0",
            "diarize": "true",
        }

        try:
            with open(file_path, "rb") as f:
                files = {
                    "audio": (filename, f, mime_type)
                }

                r = requests.post(
                    ViraService.URL,
                    data=data,
                    files=files,
                    headers=headers,
                    timeout=900
                )

            if r.status_code not in (200, 201):
                return {"error": f"Vira failed: {r.text}"}

            js = r.json()

        except requests.exceptions.RequestException as e:
            return {"exception": f"Request error: {e}"}
        except ValueError:
            return {"error": "Invalid JSON returned from Vira"}

        text = (
            js.get("data", {})
              .get("data", {})
              .get("aiResponse", {})
              .get("result", {})
              .get("text")
        )

        if not text:
            ai = js.get("data", {}).get("data", {}).get("aiResponse", {})
            if isinstance(ai, dict):
                segments = ai.get("segments")
                if isinstance(segments, list):
                    text = " ".join(
                        seg.get("text", "") for seg in segments if seg.get("text")
                    )
                elif "text" in ai:
                    text = ai.get("text")

        return {"text": text or ""}





FFMPEG_PATH = shutil.which("ffmpeg")

if not FFMPEG_PATH:
    raise RuntimeError("ffmpeg not found on system PATH")

class MediaService:
    @staticmethod
    def extract_audio(video_path: str) -> str:
        """
        Extracts WAV audio from video using ffmpeg
        Output:
          - mono
          - 16kHz
          - wav
        """
        base, _ = os.path.splitext(video_path)
        output_path = f"{base}_{uuid.uuid4().hex[:8]}.wav"

        cmd = [
            "ffmpeg",
            "-y",
            "-i", video_path,
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-acodec", "pcm_s16le",
            output_path
        ]

        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )

        return output_path
    
    
    @staticmethod
    def smart_split_audio(
        input_path: str,
        max_chunk_sec: int = 480,   
        min_chunk_sec: int = 60,
        silence_db: int = -35,
        silence_dur: float = 0.6
    ) -> list[str]:
        """
        Silence-aware audio chunking.
        Avoids cutting in the middle of sentences.
        """

        import subprocess

        work_dir = os.path.dirname(input_path)
        base = os.path.splitext(os.path.basename(input_path))[0]

        # --------------------------------------------------
        # 1. Detect silence
        # --------------------------------------------------
        detect_cmd = [
            "ffmpeg",
            "-i", input_path,
            "-af", f"silencedetect=noise={silence_db}dB:d={silence_dur}",
            "-f", "null", "-"
        ]

        proc = subprocess.Popen(
            detect_cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            text=True
        )

        silence_points = []
        for line in proc.stderr:
            if "silence_end" in line:
                try:
                    t = float(line.split("silence_end:")[1].split("|")[0].strip())
                    silence_points.append(t)
                except:
                    pass

        proc.wait()

        if not silence_points:
            return MediaService._time_split_fallback(input_path, max_chunk_sec)

        # --------------------------------------------------
        # 2. Build cut points
        # --------------------------------------------------
        cuts = []
        start = 0.0

        for sp in silence_points:
            if sp - start >= max_chunk_sec:
                valid = [s for s in silence_points if start + min_chunk_sec <= s <= sp]
                if valid:
                    cut = valid[-1]
                    cuts.append((start, cut))
                    start = cut

        
        total_duration = get_audio_duration(input_path)

        tail_len = total_duration - start

        if tail_len >= min_chunk_sec:
            cuts.append((start, None))
        else:
            if cuts:
                prev_start, _ = cuts[-1]
                cuts[-1] = (prev_start, None)


        # --------------------------------------------------
        # 3. Export chunks
        # --------------------------------------------------
        paths = []

        for i, (s, e) in enumerate(cuts):
            out = os.path.join(work_dir, f"{base}_chunk_{i:03d}.wav")

            cmd = ["ffmpeg", "-y", "-i", input_path, "-ss", str(s)]
            if e:
                cmd += ["-to", str(e)]

            cmd += [
                "-ac", "1",
                "-ar", "16000",
                "-acodec", "pcm_s16le",
                out
            ]

            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True
            )

            dur = get_audio_duration(out)
            if dur < 1.0:
                try:
                    os.remove(out)
                except:
                    pass
            else:
                paths.append(out)


        return paths

    @staticmethod
    def _time_split_fallback(path: str, sec: int) -> list[str]:
        base = os.path.splitext(path)[0]
        dir_ = os.path.dirname(path)
        pattern = os.path.basename(base) + "_chunk_%03d.wav"

        subprocess.run(
            [
                "ffmpeg", "-y", "-i", path,
                "-f", "segment",
                "-segment_time", str(sec),
                "-ac", "1",
                "-ar", "16000",
                "-acodec", "pcm_s16le",
                os.path.join(dir_, pattern)
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )

        chunks = []
        for f in sorted(os.listdir(dir_)):
            if not f.startswith(os.path.basename(base) + "_chunk_"):
                continue

            full = os.path.join(dir_, f)
            dur = get_audio_duration(full)

            if dur < 1.0:
                try:
                    os.remove(full)
                except:
                    pass
                continue

            chunks.append(full)

        return chunks
        
        
        
    
def download_temp_file(url: str, timeout=60) -> str:
    response = requests.get(url, stream=True, timeout=timeout)
    response.raise_for_status()

    suffix = os.path.splitext(urlparse(url).path)[1] or ".bin"

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    for chunk in response.iter_content(chunk_size=8192):
        if chunk:
            tmp.write(chunk)
    tmp.close()
    return tmp.name    




import requests
import logging

logger = logging.getLogger("core")

# class SummaryService:
#     ENDPOINT = "https://dadmatech.gw.isahab.ir/summarize/v1/summarize"
#     TIMEOUT = 30

#     @classmethod
#     def summarize(cls, text: str) -> str:
#         if not text or len(text.strip()) < 20:
#             return ""

#         payload = {
#             "input": text
#         }

#         headers = {
#             "Content-Type": "application/json",
#             "gateway-token": os.getenv("SUMMARY_API_TOKEN"),
#         }

#         try:
#             resp = requests.post(
#                 cls.ENDPOINT,
#                 json=payload,
#                 headers=headers,
#                 timeout=cls.TIMEOUT,
#             )
#             resp.raise_for_status()

#             data = resp.json()
#             return (data.get("data") or "").strip()

#         except Exception as e:
#             logger.error(f"[SUMMARY ERROR] {e}", exc_info=True)
#             return ""



class SummaryService:
    BASE_URL = os.getenv(
        "METIS_OPENAI_BASE_URL",
        "https://api.metisai.ir/openai/v1"
    )
    MODEL = os.getenv("SUMMARY_MODEL", "gpt-4.1-nano")
    TIMEOUT = 60

    @classmethod
    def summarize(cls, text: str) -> str:
        if not text or len(text.strip()) < 50:
            return ""

        url = f"{cls.BASE_URL}/chat/completions"

        payload = {
            "model": cls.MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "این متن خروجی تبدیل گفتار به نوشتار (STT) است و ممکن است "
                        "شامل تکرار، خطاهای گفتاری و جملات ناقص باشد. "
                        "لطفاً مفهوم اصلی، موضوعات کلیدی و پیام کلی سخنران را "
                        "به‌صورت یک خلاصه‌ی روان و منسجم به زبان فارسی استخراج کن."
                    )
                },
                {
                    "role": "user",
                    "content": text
                }
            ],
            "temperature": 0.3,
            "max_tokens": 500
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('METIS_API_KEY')}",
        }

        try:
            resp = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=cls.TIMEOUT
            )
            resp.raise_for_status()

            data = resp.json()

            return (
                data["choices"][0]["message"]["content"].strip()
                if data.get("choices")
                else ""
            )

        except Exception as e:
            logger.error(f"[SUMMARY ERROR] {e}", exc_info=True)
            return ""
