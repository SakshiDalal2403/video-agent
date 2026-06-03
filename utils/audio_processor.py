import yt_dlp
import glob
import os
import subprocess

DOWNLOAD_DIR='downloads'
os.makedirs(DOWNLOAD_DIR,exist_ok=True)

def log_audio(message: str):
    print(f"[audio] {message}", flush=True)


def run_ffmpeg(command: list[str]):
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr[-1000:]}")

def download_youtube_audio(url :str) ->str:
    output_path = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_path,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }
        ],
        # suppress the downloads
        "quiet": True, 
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info).replace(".webm", ".wav").replace(".m4a", ".wav")
    return filename


# data = download_youtube_audio("https://www.youtube.com/watch?v=mtiOK2QG9Q0")


def convert_to_wav(input_path: str) -> str:
    """Convert any audio/video file to WAV format using ffmpeg."""
    output_path = os.path.splitext(input_path)[0] + "_converted.wav"
    run_ffmpeg([
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        output_path,
    ])
    return output_path

# data_final = convert_to_wav(data)


def chunk_audio(wav_path : str , chunk_minutes : int = 10) -> list:
    chunk_seconds = chunk_minutes * 60
    chunk_pattern = f"{wav_path}_chunk_%03d.wav"
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
    return sorted(glob.glob(f"{wav_path}_chunk_*.wav"))


# print(chunk_audio(data_final))


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


