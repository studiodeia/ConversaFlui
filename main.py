import os
import subprocess
import base64
import logging
import tempfile
import shutil
from fastapi import FastAPI, HTTPException, File, UploadFile, Body
from fastapi.responses import FileResponse, JSONResponse
import requests
from typing import Dict

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Get PORT from environment variable, default to 8000 if not set (for local testing)
PORT = int(os.environ.get("PORT", 8000))

app = FastAPI(title="ConversaFlui API", version="1.0.0")

# --- Helper Functions ---

def download_file(url: str, destination: str):
    """Downloads a file from a URL to a destination path."""
    logger.info(f"Attempting to download file from: {url}")
    try:
        with requests.get(url, stream=True, timeout=30) as r: # Added timeout
            r.raise_for_status()  # Raise an exception for bad status codes
            with open(destination, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        logger.info(f"File downloaded successfully to: {destination}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error downloading file from {url}: {e}")
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred during download from {url}: {e}")
        return False

def convert_to_mp3(input_path: str, output_path: str) -> bool:
    """Converts an audio file to MP3 using FFmpeg."""
    logger.info(f"Attempting to convert {input_path} to MP3 at {output_path}")
    command = [
        "ffmpeg",
        "-i", input_path,
        "-vn",          # Disable video recording
        "-acodec", "libmp3lame", # Use LAME MP3 encoder
        "-ab", "192k",  # Audio bitrate
        "-ar", "44100", # Audio sampling frequency
        "-ac", "2",     # Number of audio channels (stereo)
        "-y",           # Overwrite output file if it exists
        output_path
    ]
    try:
        # Using shell=False is generally safer
        process = subprocess.run(command, check=True, capture_output=True, text=True)
        logger.info(f"FFmpeg conversion successful for {input_path}")
        logger.debug(f"FFmpeg stdout: {process.stdout}")
        logger.debug(f"FFmpeg stderr: {process.stderr}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg conversion failed for {input_path}.")
        logger.error(f"Command: {' '.join(command)}")
        logger.error(f"Return code: {e.returncode}")
        logger.error(f"Stderr: {e.stderr}")
        logger.error(f"Stdout: {e.stdout}")
        return False
    except FileNotFoundError:
        logger.error("FFmpeg command not found. Is FFmpeg installed and in the system's PATH?")
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred during FFmpeg conversion: {e}")
        return False

# --- API Endpoints ---

@app.get("/health", summary="Health Check", tags=["System"])
async def health_check():
    """Basic health check endpoint for monitoring."""
    logger.info("Health check endpoint called.")
    return {"status": "ok"}

@app.post("/audio/convert-to-mp3",
          summary="Convert Audio URL to MP3",
          response_class=FileResponse,
          tags=["Audio Processing"])
async def convert_audio_to_mp3(payload: Dict[str, str] = Body(...)):
    """
    Downloads audio from a URL, converts it to MP3 using FFmpeg,
    and returns the MP3 file.
    Expects JSON payload: {"audio_url": "..."}
    """
    audio_url = payload.get("audio_url")
    if not audio_url:
        logger.warning("Missing 'audio_url' in request payload.")
        raise HTTPException(status_code=400, detail="Missing 'audio_url' in request payload.")

    logger.info(f"Received request to convert audio from URL: {audio_url}")

    # Create temporary directory for processing
    with tempfile.TemporaryDirectory() as temp_dir:
        original_filename = os.path.basename(requests.utils.urlparse(audio_url).path)
        # Try to keep original extension, default if none
        base_name, _ = os.path.splitext(original_filename)
        if not base_name: # Handle cases where URL path might not have a filename
             base_name = "audio_download"
        input_file_path = os.path.join(temp_dir, f"{base_name}_input") # Temp name before knowing extension
        output_file_path = os.path.join(temp_dir, f"{base_name}_output.mp3")

        # 1. Download the file
        if not download_file(audio_url, input_file_path):
            raise HTTPException(status_code=500, detail="Failed to download audio file from URL.")

        # Rename input file if we can guess extension (helps ffmpeg sometimes)
        try:
            content_type = requests.head(audio_url, timeout=10).headers.get('content-type')
            if content_type:
                import mimetypes
                ext = mimetypes.guess_extension(content_type)
                if ext:
                    new_input_path = os.path.join(temp_dir, f"{base_name}{ext}")
                    os.rename(input_file_path, new_input_path)
                    input_file_path = new_input_path
                    logger.info(f"Renamed downloaded file to {input_file_path} based on content-type: {content_type}")
        except Exception as e:
            logger.warning(f"Could not determine or rename based on content-type: {e}")


        # 2. Convert to MP3 using FFmpeg
        if not convert_to_mp3(input_file_path, output_file_path):
            raise HTTPException(status_code=500, detail="Failed to convert audio file to MP3 using FFmpeg.")

        # 3. Return the converted MP3 file
        logger.info(f"Conversion complete. Returning MP3 file: {output_file_path}")
        # Need to copy the file out of the temp dir before returning, as the dir will be deleted.
        # A more robust solution might stream directly or use a persistent temp location if needed.
        # For simplicity here, we copy it.
        final_output_path = os.path.join(tempfile.gettempdir(), os.path.basename(output_file_path))
        shutil.copy2(output_file_path, final_output_path)

        # Return FileResponse - FastAPI handles cleanup of the copied file after sending
        return FileResponse(path=final_output_path, media_type='audio/mpeg', filename=os.path.basename(output_file_path))

    # Note: The temporary directory and its contents are automatically cleaned up
    # when exiting the 'with' block, except for the file copied out for the response.

@app.post("/audio/encode-base64",
          summary="Encode MP3 to Base64",
          tags=["Audio Processing"])
async def encode_audio_to_base64(audio_file: UploadFile = File(...)):
    """
    Receives an MP3 audio file upload, encodes its content to Base64,
    and returns the Base64 string in a JSON response.
    """
    logger.info(f"Received request to encode file: {audio_file.filename} (type: {audio_file.content_type})")

    if not audio_file.content_type or not audio_file.content_type.startswith("audio/"):
        # Basic check, could be more specific (e.g., 'audio/mpeg')
        logger.warning(f"Invalid file type uploaded: {audio_file.content_type}")
        raise HTTPException(status_code=400, detail=f"Invalid file type. Expected an audio file, got {audio_file.content_type}")

    try:
        # Read the file content directly from the upload
        contents = await audio_file.read()
        logger.info(f"Read {len(contents)} bytes from uploaded file.")

        # Encode to Base64
        base64_encoded_string = base64.b64encode(contents).decode('utf-8')
        logger.info("Successfully encoded audio file to Base64.")

        # Return the Base64 string in JSON format
        return JSONResponse(content={"base64_string": base64_encoded_string})

    except Exception as e:
        logger.error(f"Error processing uploaded file {audio_file.filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process or encode the audio file: {e}")
    finally:
        # Ensure the file stream is closed
        await audio_file.close()
        logger.debug(f"Closed file stream for {audio_file.filename}")


# --- Main Execution (for local testing) ---
if __name__ == "__main__":
    logger.info(f"Starting Uvicorn server locally on port {PORT}")
    import uvicorn
    # Use 0.0.0.0 to be accessible on the network, Railway uses $PORT
    uvicorn.run(app, host="0.0.0.0", port=PORT)

# Note: Railway will use the CMD in the Dockerfile to start the server,
# typically like: uvicorn main:app --host 0.0.0.0 --port $PORT