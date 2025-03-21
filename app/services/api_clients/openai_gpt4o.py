# app/services/api_clients/openai_gpt4o.py 

import os
import logging
import time
from typing import Tuple, Optional, Callable
from openai import OpenAI
from app.services import file_service

class OpenAIGPT4oTranscriptionAPI:
    """
    Integration with OpenAI GPT 4o Transcribe using synchronous requests.
    When a file is split (because it exceeds the 25MB limit), each chunk is 
    transcribed independently (without any context) and then the individual 
    transcripts are aggregated.
    """
    def __init__(self, api_key: str) -> None:
        # Avoid logging the actual API key.
        self.api_key = api_key
        logging.info("Initialized OpenAIGPT4oTranscriptionAPI.")

    def transcribe(self, audio_file_path: str, language_code: str,
                   progress_callback: Optional[Callable[[str], None]] = None) -> Tuple[str, str]:
        if progress_callback:
            progress_callback(f"Transcribing file {audio_file_path}")
        else:
            logging.info(f"Transcribing file {audio_file_path}")

        client = OpenAI(api_key=self.api_key)
        try:
            if os.path.getsize(audio_file_path) > 25 * 1024 * 1024:
                if progress_callback:
                    progress_callback("File too large – splitting into chunks.")
                else:
                    logging.info("File too large – splitting into chunks.")
                return self.split_and_transcribe(audio_file_path, language_code, progress_callback)
            else:
                abs_path = os.path.abspath(audio_file_path)
                if not file_service.validate_file_path(abs_path, os.path.dirname(audio_file_path)):
                    raise ValueError("Audio file path is not allowed.")
                with open(abs_path, "rb") as audio_file:
                    transcript = client.audio.transcriptions.create(
                        model="gpt-4o-transcribe",
                        file=audio_file,
                        response_format="text"
                    )
                    transcription_text = transcript if isinstance(transcript, str) else transcript.text
        except Exception as e:
            error_msg = f"Error transcribing file: {e}"
            if progress_callback:
                progress_callback(error_msg)
            logging.error(error_msg)
            return "", ""
        detected_language = language_code if language_code != 'auto' else 'en'
        if progress_callback:
            progress_callback("Transcription completed.")
        return transcription_text, detected_language

    def split_and_transcribe(self, audio_file_path: str, language_code: str,
                             progress_callback: Optional[Callable[[str], None]] = None) -> Tuple[str, str]:
        if progress_callback:
            progress_callback(f"Splitting file {audio_file_path}")
        else:
            logging.info(f"Splitting file {audio_file_path}")
        temp_dir = os.path.dirname(audio_file_path)
        chunk_files = file_service.split_audio_file(audio_file_path, temp_dir, progress_callback)
        client = OpenAI(api_key=self.api_key)
        transcription_texts = []
        total_chunks = len(chunk_files)
        for idx, chunk_path in enumerate(chunk_files):
            if progress_callback:
                progress_callback(f"Transcribing chunk {idx+1}/{total_chunks}")
            else:
                logging.debug(f"Transcribing chunk {idx+1}/{total_chunks}")
            chunk_text = self._transcribe_chunk(client, chunk_path, idx, total_chunks, progress_callback)
            transcription_texts.append(chunk_text)
        file_service.remove_files(chunk_files)
        detected_language = language_code if language_code != 'auto' else 'en'
        full_transcription = " ".join(transcription_texts)
        logging.info("Transcription aggregated successfully.")
        return full_transcription, detected_language

    def _transcribe_chunk(self, client: OpenAI, chunk_path: str, idx: int, total_chunks: int,
                            progress_callback: Optional[Callable[[str], None]] = None,
                            max_retries: int = 3) -> str:
        transcript_text = ""
        last_error = None
        for attempt in range(max_retries):
            if progress_callback:
                progress_callback(f"Transcribing chunk {idx+1}/{total_chunks}, attempt {attempt+1}")
            else:
                logging.debug(f"Transcribing chunk {idx+1}/{total_chunks}, attempt {attempt+1}")
            try:
                with open(chunk_path, "rb") as audio_file:
                    response = client.audio.transcriptions.create(
                        model="gpt-4o-transcribe",
                        file=audio_file,
                        response_format="text"
                    )
                    text = response if isinstance(response, str) else response.text
                if text.strip():
                    transcript_text = text
                    break  # Successful transcription for this chunk.
            except Exception as e:
                last_error = e
                error_detail = f"Error transcribing chunk {idx+1} on attempt {attempt+1}: {e}"
                if progress_callback:
                    progress_callback(error_detail)
                logging.error(error_detail)
            time.sleep(2)
        if not transcript_text:
            final_error = f"Chunk {idx+1} failed after {max_retries} attempts. Last error: {last_error}"
            if progress_callback:
                progress_callback(final_error)
            logging.error(final_error)
        return transcript_text
