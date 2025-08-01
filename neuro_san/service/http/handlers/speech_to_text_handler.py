# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT
"""
Speech-to-Text API Handler
Converts MP3 audio input to text output
"""
import os
from io import BytesIO
from typing import Any
from typing import Dict

import speech_recognition as sr
from pydub import AudioSegment

from neuro_san.service.http.handlers.base_request_handler import \
    BaseRequestHandler

"""
Test endpoint with curl

curl -X POST \
    -F "audio=@audio.mp3;type=audio/mpeg" \
    http://127.0.0.1:8080/api/v1/speech_to_text
"""


class SpeechToTextHandler(BaseRequestHandler):
    """
    Handler class for neuro-san "speech_to_text" API call.
    Takes MP3 audio input and returns text output.
    """

    def _validate_mp3_format(self, file_data: bytes) -> bool:
        """
        Validate that the uploaded file is a valid MP3 format.

        :param file_data: Binary data of the uploaded file
        :return: True if valid MP3, False otherwise
        """
        if len(file_data) < 4:
            return False

        # Check for MP3 frame header (simplified validation)
        # MP3 frames typically start with 0xFF followed by 0xFB, 0xFA, or 0xF3
        if file_data[0] == 0xFF and file_data[1] in [0xFB, 0xFA, 0xF3]:
            return True

        # Check for ID3 tag (alternative MP3 format)
        if file_data[:3] == b"ID3":
            return True

        return False

    def _transcribe_mp3(self, mp3_data: bytes) -> str:
        """
        Transcribe MP3 audio to text.

        :param mp3_data: Binary MP3 audio data
        :return: Transcribed text
        """
        # Convert MP3 to WAV (temporary file)

        # Load MP3 from in-memory bytes
        mp3_buffer = BytesIO(mp3_data)
        sound = AudioSegment.from_file(mp3_buffer, format="mp3")
        wav_path = "temp.wav"
        sound.export(wav_path, format="wav")

        recognizer = sr.Recognizer()
        text = ""

        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)  # grab the whole file
            try:
                text = recognizer.recognize_google(audio_data)
            except sr.UnknownValueError:
                text = "Could not understand the audio."
            except sr.RequestError as e:
                text = f"API request error: {e}"

        # Clean up
        os.remove(wav_path)

        return text

    async def post(self):
        """
        Implementation of POST request handler for "speech_to_text" API call.
        Expects multipart/form-data with MP3 file upload in 'audio' field
        Returns: JSON with transcribed text: {"text": "transcribed content"}
        """
        metadata: Dict[str, Any] = self.get_metadata()
        self.application.start_client_request(metadata, "/api/v1/speech_to_text")

        try:
            # Check if request contains file data
            if not hasattr(self.request, "files") or "audio" not in self.request.files:
                self.set_status(400)
                self.set_header("Content-Type", "application/json")
                self.write(
                    {"error": "Missing 'audio' file in multipart/form-data request"}
                )
                return

            # Get the uploaded file
            file_info = self.request.files["audio"][0]
            filename = file_info["filename"]
            file_data = file_info["body"]
            content_type = file_info.get("content_type", "")

            # Validate file format
            if not content_type.startswith("audio/") and not filename.lower().endswith(
                ".mp3"
            ):
                self.set_status(400)
                self.set_header("Content-Type", "application/json")
                self.write({"error": "File must be an MP3 audio file"})
                return

            # Validate MP3 format
            if not self._validate_mp3_format(file_data):
                self.set_status(400)
                self.set_header("Content-Type", "application/json")
                self.write({"error": "Invalid MP3 file format"})
                return

            # Check file size (limit to 10MB for this example)
            max_file_size = 10 * 1024 * 1024  # 10MB
            if len(file_data) > max_file_size:
                self.set_status(400)
                self.set_header("Content-Type", "application/json")
                error_msg = (
                    f"File too large. Maximum size is {max_file_size // (1024*1024)}MB"
                )
                self.write({"error": error_msg})
                return

            # Transcribe the audio (mock implementation)
            transcribed_text = self._transcribe_mp3(file_data)

            # Return transcribed text as JSON
            self.set_header("Content-Type", "application/json")
            response = {
                "text": transcribed_text,
                "filename": filename,
                "file_size_bytes": len(file_data),
            }
            self.write(response)

        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.process_exception(exc)
        finally:
            self.do_finish()
            self.application.finish_client_request(metadata, "/api/v1/speech_to_text")

    async def options(self):
        """
        Handle CORS preflight requests
        """
        self.set_status(200)
        self.do_finish()
