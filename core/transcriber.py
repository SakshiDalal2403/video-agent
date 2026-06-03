import os
import requests
import time
from pydub import AudioSegment

SARVAM_PIECE_SECONDS = 25

HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY") or os.getenv("HF_TOKEN")
HF_WHISPER_MODEL = os.getenv("HF_WHISPER_MODEL", "openai/whisper-small")
HF_STT_URL = os.getenv(
    "HF_STT_URL",
    f"https://router.huggingface.co/hf-inference/models/{HF_WHISPER_MODEL}",
)

SARVAM_API_KEY =os.getenv("SARVAM_API_KEY")
SARVAM_STT_TRANSLATE_URL = "https://api.sarvam.ai/speech-to-text-translate"
SARVAM_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v2.5")

def transcribe_chunk_huggingface(chunk_path: str) -> str:
    if not HF_API_KEY:
        raise RuntimeError("HUGGINGFACE_API_KEY or HF_TOKEN is not set in environment / .env")

    headers = {"Authorization": f"Bearer {HF_API_KEY}"}

    with open(chunk_path, "rb") as f:
        audio_data = f.read()

    last_response = None
    for attempt in range(3):
        response = requests.post(
            HF_STT_URL,
            headers=headers,
            data=audio_data,
            timeout=300,
        )

        if response.status_code not in {429, 503, 504}:
            break

        last_response = response
        time.sleep(2 * (attempt + 1))
    else:
        response = last_response

    if not response.ok:
        print(f"\nHugging Face returned {response.status_code}")
        print(f"Response body: {response.text}\n")
        response.raise_for_status()

    return response.json().get("text", "")

def _send_to_sarvam(piece_path: str) -> str:
    """Send one ≤30s WAV file to Sarvam and return the English transcript."""
    headers = {"api-subscription-key": SARVAM_API_KEY}

    with open(piece_path, "rb") as f:
        files = {"file": (os.path.basename(piece_path), f, "audio/wav")}
        data = {"model": SARVAM_MODEL, "with_diarization": "false"}
        response = requests.post(
            SARVAM_STT_TRANSLATE_URL,
            headers=headers,
            files=files,
            data=data,
            timeout=120,
        )

    if not response.ok:
        print(f"\n❌ Sarvam returned {response.status_code}")
        print(f"Response body: {response.text}\n")
        response.raise_for_status()

    return response.json().get("transcript", "")


def transcribe_chunk_sarvam(chunk_path: str) -> str:
    """
    Sarvam sync API only accepts ≤30s audio. We split this chunk into
    25-second pieces, send each separately, and join the transcripts.
    """
    if not SARVAM_API_KEY:
        raise RuntimeError("SARVAM_API_KEY is not set in environment / .env")

    # headers = {"api-subscription-key":SARVAM_API_KEY}

    # with open (chunk_path,"rb") as f:
    #     files={"file" : (os.path.basename(chunk_path),f,"audio/wav")}
    #     data ={"model":SARVAM_MODEL ,"with_diarization":"false"}
    #     response =requests.post(
    #         SARVAM_STT_TRANSLATE_URL,
    #         headers=headers,
    #         files=files,
    #         data=data,
    #         timeout=300,
    #     )

    #     response.raise_for_status()

    #     return response.json().get("transcript","")


    audio = AudioSegment.from_wav(chunk_path)
    piece_ms = SARVAM_PIECE_SECONDS * 1000

    full_text = ""
    total_pieces = (len(audio) + piece_ms - 1) // piece_ms

    for i, start in enumerate(range(0, len(audio), piece_ms)):
        piece = audio[start: start + piece_ms]
        piece_path = f"{chunk_path}_sv_{i}.wav"
        piece.export(piece_path, format="wav")

        try:
            print(f"  → Sarvam piece {i + 1}/{total_pieces} ...")
            full_text += _send_to_sarvam(piece_path) + " "
        finally:
            if os.path.exists(piece_path):
                os.remove(piece_path)

    return full_text.strip()



   
def transcribe_chunk(chunk_path: str, language: str = "english") -> str:
    """
    Route one chunk to Hugging Face or Sarvam depending on language choice.
    - english  → Hugging Face Whisper API
    - hinglish → Sarvam (translates to English while transcribing)
    """
    if language.lower() == "hinglish":
        return transcribe_chunk_sarvam(chunk_path)
    return transcribe_chunk_huggingface(chunk_path)

def transcribe_all(chunks: list, language: str = "english") -> str:

    full_transcript = "" 

    engine = "Sarvam AI" if language.lower() == "hinglish" else "Hugging Face Whisper API"
    print(f"Using {engine} for transcription.")

    for i, chunk in enumerate(chunks):  

        print(f"Transcribing chunk {i + 1}/{len(chunks)}...")

        text = transcribe_chunk(chunk, language=language)  

        full_transcript += text + " "  

    print("Transcription complete.")

    return full_transcript.strip()  
         


