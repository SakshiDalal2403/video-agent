import os
import requests
import time
# from huggingface_hub import InferenceClient
from pydub import AudioSegment
from groq import Groq

SARVAM_PIECE_SECONDS = 25

# HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY") or os.getenv("HF_TOKEN")
# HF_WHISPER_MODEL = os.getenv("HF_WHISPER_MODEL", "openai/whisper-large-v3")
# HF_PROVIDER = os.getenv("HF_PROVIDER", "fal-ai")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

SARVAM_API_KEY =os.getenv("SARVAM_API_KEY")
SARVAM_STT_TRANSLATE_URL = "https://api.sarvam.ai/speech-to-text-translate"
SARVAM_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v2.5")

# Commented out Hugging Face transcription
# def transcribe_chunk_huggingface(chunk_path: str) -> str:
#     if not HF_API_KEY:
#         raise RuntimeError("HUGGINGFACE_API_KEY or HF_TOKEN is not set in environment / .env")
# 
#     client = InferenceClient(provider=HF_PROVIDER, api_key=HF_API_KEY)
#     last_error = None
#     for attempt in range(3):
#         try:
#             result = client.automatic_speech_recognition(
#                 chunk_path,
#                 model=HF_WHISPER_MODEL,
#             )
#             return result.text
#         except Exception as exc:
#             last_error = exc
#             if attempt == 2:
#                 break
#             time.sleep(2 * (attempt + 1))
# 
#     print(f"\nHugging Face transcription failed: {last_error}\n")
#     raise last_error

def transcribe_chunk_groq(chunk_path: str) -> str:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set in environment / .env")

    client = Groq(api_key=GROQ_API_KEY)
    last_error = None
    for attempt in range(3):
        try:
            with open(chunk_path, "rb") as f:
                transcription = client.audio.transcriptions.create(
                    file=(chunk_path, f.read()),
                    model="whisper-large-v3",
                    response_format="text",
                    language="en",
                )
            return transcription
        except Exception as exc:
            last_error = exc
            if attempt == 2:
                break
            time.sleep(2 ** (attempt + 1))

    print(f"\nGroq Whisper transcription failed: {last_error}\n")
    raise last_error


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
    Route one chunk to Groq or Sarvam depending on language choice.
    - english  → Groq Whisper API
    - hinglish → Sarvam (translates to English while transcribing)
    """
    if language.lower() == "hinglish":
        return transcribe_chunk_sarvam(chunk_path)
    # return transcribe_chunk_huggingface(chunk_path)  # Commented out Hugging Face
    return transcribe_chunk_groq(chunk_path)

def transcribe_all(chunks: list, language: str = "english") -> str:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    engine = "Sarvam AI" if language.lower() == "hinglish" else "Groq Whisper API"
    print(f"Using {engine} for transcription.")

    results = {}

    def _transcribe_indexed(args):
        idx, chunk = args
        print(f"Transcribing chunk {idx + 1}/{len(chunks)}...")
        text = transcribe_chunk(chunk, language=language)
        return idx, text

    with ThreadPoolExecutor(max_workers=min(len(chunks), 4)) as pool:
        futures = {pool.submit(_transcribe_indexed, (i, chunk)): i for i, chunk in enumerate(chunks)}
        for future in as_completed(futures):
            idx, text = future.result()
            results[idx] = text

    full_transcript = " ".join(results[i] for i in sorted(results))

    print("Transcription complete.")
    return full_transcript.strip()
