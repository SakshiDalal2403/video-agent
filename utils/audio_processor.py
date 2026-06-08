import yt_dlp #utube se audio download 
import glob  #used to search files
import os
import subprocess #run external commands like ffmpeg

DOWNLOAD_DIR='downloads'
os.makedirs(DOWNLOAD_DIR,exist_ok=True)
YTDLP_TIMEOUT_SECONDS = int(os.getenv("YTDLP_TIMEOUT_SECONDS", "600"))
FFMPEG_TIMEOUT_SECONDS = int(os.getenv("FFMPEG_TIMEOUT_SECONDS", "600"))

def log_audio(message: str):
    print(f"[audio] {message}", flush=True)

#executes the ffmpeg command

def run_ffmpeg(command: list[str]):
    try:
        result = subprocess.run(
            command,
            #store output
            stdout=subprocess.PIPE,
            #store error
            stderr=subprocess.PIPE,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"FFmpeg timed out after {FFMPEG_TIMEOUT_SECONDS} seconds.") from exc

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr[-1000:]}")


#Utube audio downlaod function
def download_youtube_audio(url :str) ->str:
    output_path = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_path,
        #after downloading convert it to wav format
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }
        ],
        # suppress the downloads
        "quiet": True, 
        "socket_timeout": YTDLP_TIMEOUT_SECONDS,
        "retries": 3,
        "fragment_retries": 3,
    }

    # Use cookies.txt if present (bypasses YouTube bot-detection on cloud hosts like Render)
    cookies_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cookies.txt")
    if os.path.exists(cookies_path):
        ydl_opts["cookiefile"] = cookies_path
        log_audio(f"Using cookies file for YouTube authentication: {cookies_path}")
    else:
        log_audio("No cookies.txt found — proceeding without authentication cookies.")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info).replace(".webm", ".wav").replace(".m4a", ".wav")
    return filename


# data = download_youtube_audio("https://www.youtube.com/watch?v=mtiOK2QG9Q0")


#any file --> convert it to wav format

def convert_to_wav(input_path: str) -> str:
    """Convert any audio/video file to WAV format using ffmpeg."""
    output_path = os.path.splitext(input_path)[0] + "_converted.wav"
    log_audio("Converting media to 16kHz mono WAV...")
    run_ffmpeg([
        "ffmpeg",
        "-y",  #overwrite allowed
        "-i", #inpput file
        input_path,
        "-vn", #remove video
        "-ac", #mono audio channel
        "1",
        "-ar",
        "16000",
        output_path,
    ])
    return output_path

# data_final = convert_to_wav(data)

#audio chunkingg function
def chunk_audio(wav_path : str , chunk_minutes : int = 10) -> list:
    chunk_seconds = chunk_minutes * 60
    chunk_pattern = f"{wav_path}_chunk_%03d.wav"
    log_audio("Splitting WAV into transcript chunks...")
    run_ffmpeg([
        "ffmpeg",
        "-y",
        "-i",
        wav_path,
        "-f",
        "segment",
        "-segment_time",
        str(chunk_seconds),
        "-c",
        "copy",
        chunk_pattern,
    ])
    chunks = sorted(glob.glob(f"{wav_path}_chunk_*.wav"))
    if not chunks:
        raise RuntimeError("Audio chunking finished but no chunks were created.")
    return chunks


# print(chunk_audio(data_final))

#main controller function
def process_input(source: str) -> list:
    if source.startswith("http://") or source.startswith("https://"):
        log_audio("Detected YouTube URL. Downloading audio...")
        wav_path = download_youtube_audio(source)
    else:
        log_audio("Detected local file. Converting to WAV...")
        wav_path = convert_to_wav(source)

    log_audio(f"WAV ready at {wav_path}. Chunking audio...")
    chunks = chunk_audio(wav_path)
    log_audio(f"Audio ready - {len(chunks)} chunk(s) created.")
    return chunks

            # process_input()

#         |
#         |
#         v

# Is input URL?
        
# YES ---------------- NO
#  |                   |
#  v                   v

# download           convert
# youtube            local file
# audio              to WAV

#         \          /
#          \        /
#           v      v

#         WAV file

#            |
#            v

#      chunk_audio()

#            |
#            v

# [chunk1.wav,
#  chunk2.wav,
#  chunk3.wav]

