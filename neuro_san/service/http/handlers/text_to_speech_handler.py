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
Text-to-Speech API Handler
Converts text input to MP3 audio output
"""
import json
from io import BytesIO
from typing import Any
from typing import Dict

from gtts import gTTS

from neuro_san.service.http.handlers.base_request_handler import \
    BaseRequestHandler

"""
Test endpoint with curl

curl -X POST \
    -H "Content-Type: application/json" \
    -d '{"text": "Convert text to speech"}' \
    http://127.0.0.1:8080/api/v1/text_to_speech \
    --output audio.mp3
"""


class TextToSpeechHandler(BaseRequestHandler):
    """
    Handler class for neuro-san "text_to_speech" API call.
    Takes text input and returns MP3 audio output.
    """

    async def post(self):
        """
        Implementation of POST request handler for "text_to_speech" API call.
        Expects JSON input: {"text": "string to convert to speech"}
        Returns: MP3 audio file
        """
        metadata: Dict[str, Any] = self.get_metadata()
        self.application.start_client_request(metadata, "/api/v1/text_to_speech")

        try:
            # Parse JSON body
            request_data = json.loads(self.request.body)

            # Validate input
            if "text" not in request_data:
                self.set_status(400)
                self.write({"error": "Missing 'text' field in request body"})
                return

            text = request_data["text"]
            if not isinstance(text, str) or not text.strip():
                self.set_status(400)
                self.write({"error": "Text field must be a non-empty string"})
                return

            # Generate MP3 audio (mock implementation)
            text_to_speech = gTTS(text=text, lang="en")

            mp3_fp = BytesIO()
            text_to_speech.write_to_fp(mp3_fp)

            mp3_data = mp3_fp.getvalue()

            # Set appropriate headers for MP3 file response
            self.set_header("Content-Type", "audio/mpeg")
            self.set_header("Content-Disposition", 'attachment; filename="speech.mp3"')
            self.set_header("Content-Length", str(len(mp3_data)))

            # Write binary MP3 data
            self.write(mp3_data)

        except json.JSONDecodeError:
            self.set_status(400)
            self.write({"error": "Invalid JSON in request body"})
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.process_exception(exc)
        finally:
            self.do_finish()
            self.application.finish_client_request(metadata, "/api/v1/text_to_speech")

    async def options(self):
        """
        Handle CORS preflight requests
        """
        self.set_status(200)
        self.do_finish()
