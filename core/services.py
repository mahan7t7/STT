# core/services.py
import json
import time
import requests
import os
import subprocess
import uuid
from django.conf import settings
from django.contrib.sites.models import Site



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
        mime_type = "audio/mpeg" if filename.lower().endswith(".mp3") else "audio/wav"
        model_type = "telephony" if filename.lower().endswith(".mp3") else "default"

        files = {
            "audio": (filename, open(file_path, "rb"), mime_type)
        }

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
            r = requests.post(ViraService.URL, data=data, files=files, headers=headers, timeout=900)
        except Exception as e:
            return {"exception": f"Request error: {str(e)}"}

        if r.status_code not in (200, 201):
            return {"error": f"Vira failed: {r.text}"}

        js = r.json()

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
                    text = " ".join(seg.get("text", "") for seg in segments if seg.get("text"))
                elif "text" in ai:
                    text = ai.get("text")

        return {"text": text or ""}






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