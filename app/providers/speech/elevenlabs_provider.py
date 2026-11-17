from app.providers.speech.base import BaseSpeechProvider


class ElevenLabsProvider(BaseSpeechProvider):
    """
    Speech-to-text via ElevenLabs Scribe v2.

    Handles two response shapes returned by the API:
      - Standard (single-channel): `response.text` / `response.words[]`
      - Multichannel:              `response.transcripts[]` (one per channel)

    When diarization is enabled, word-level speaker IDs are used to produce a
    speaker-labelled transcript that helps the LLM generate better meeting minutes.
    """

    provider_name = "elevenlabs"

    def transcribe_file(self, audio_path: str) -> str:
        try:
            from elevenlabs import ElevenLabs
        except ImportError as exc:
            raise RuntimeError(
                "elevenlabs is not installed. Run: pip install elevenlabs"
            ) from exc

        if not self.validate_key():
            raise RuntimeError("ElevenLabs API key is not configured.")

        client = ElevenLabs(api_key=self.api_key)

        # Pass the open file handle (not bytes) as the SDK expects
        try:
            with open(audio_path, "rb") as audio_file:
                response = client.speech_to_text.convert(
                    file=audio_file,
                    model_id="scribe_v2",
                    diarize=True,               # speaker identification
                    timestamps_granularity="word",  # needed to sort multichannel words
                )
        except Exception as exc:
            raise self._wrap_auth_error(exc) from exc

        return self._extract_transcript(response)

    @staticmethod
    def _wrap_auth_error(exc: Exception) -> Exception:
        """Turn an opaque 401 ApiError into an actionable message."""
        status = getattr(exc, "status_code", None)
        body = getattr(exc, "body", None)
        detail = ""
        if isinstance(body, dict):
            d = body.get("detail") or {}
            if isinstance(d, dict):
                detail = str(d.get("message") or d.get("status") or "")

        if status == 401:
            # ElevenLabs returns 401 for BOTH bad keys and exhausted quota.
            if "quota" in detail.lower() or "character" in detail.lower():
                return RuntimeError(
                    "ElevenLabs quota exhausted (401 quota_exceeded). "
                    "The account has no speech-to-text characters left. "
                    "Upgrade the plan or add credits at "
                    "https://elevenlabs.io/app/settings/billing, or switch "
                    "SPEECH_PROVIDER to another provider."
                )
            return RuntimeError(
                "ElevenLabs API key was rejected (401 invalid_api_key). "
                "The key in your .env is invalid, expired or revoked. "
                "Generate a new key at https://elevenlabs.io/app/settings/api-keys "
                "and update ELEVENLABS_API_KEY, then redeploy."
            )
        if status == 403:
            return RuntimeError(
                "ElevenLabs denied access (403). The key is valid but lacks "
                "speech-to-text (Scribe) permission, or the account has no credits."
            )
        if status == 429:
            return RuntimeError("ElevenLabs rate limit or quota exhausted (429).")
        return exc

    # ── Response parsing ────────────────────────────────────────────────────

    @staticmethod
    def _extract_transcript(response) -> str:
        """
        Route the response to the correct parser based on its shape.
        Multichannel files (stereo conference recordings, etc.) return
        `response.transcripts`; everything else returns `response.text`.
        """
        # Multichannel response — merge channels sorted by timestamp
        if hasattr(response, "transcripts") and response.transcripts:
            return ElevenLabsProvider._merge_multichannel(response)

        # Single-channel with word-level diarization
        if hasattr(response, "words") and response.words:
            return ElevenLabsProvider._build_diarized_transcript(response.words)

        # Plain text fallback (no diarization data)
        if hasattr(response, "text") and response.text:
            return response.text.strip()

        if isinstance(response, dict):
            return response.get("text", "").strip()

        raise RuntimeError(f"Unexpected ElevenLabs response: {response!r}")

    @staticmethod
    def _build_diarized_transcript(words) -> str:
        """
        Collapse word-level diarization results into labelled speaker blocks.
        Produces clean output for the LLM:
            [speaker_0]: Hello everyone, let's get started.
            [speaker_1]: Thanks for joining.
        Falls back to plain text when only one speaker is detected.
        """
        segments: list[tuple[str | None, str]] = []
        current_speaker = None
        current_words: list[str] = []

        for word in words:
            # Skip spacing/punctuation tokens
            if hasattr(word, "type") and word.type != "word":
                continue
            speaker = getattr(word, "speaker_id", None)
            if speaker != current_speaker:
                if current_words:
                    segments.append((current_speaker, " ".join(current_words)))
                current_speaker = speaker
                current_words = [word.text]
            else:
                current_words.append(word.text)

        if current_words:
            segments.append((current_speaker, " ".join(current_words)))

        if not segments:
            return ""

        unique_speakers = {s for s, _ in segments if s}
        if len(unique_speakers) > 1:
            return "\n\n".join(
                f"[{speaker or 'Unknown'}]: {text}" for speaker, text in segments
            )
        # Single speaker — return plain paragraph text
        return " ".join(text for _, text in segments)

    @staticmethod
    def _merge_multichannel(response) -> str:
        """
        Merge a multichannel response into a single time-ordered conversation.
        Each channel maps deterministically to a speaker:
            channel 0 → [speaker_0], channel 1 → [speaker_1], …

        Words from all channels are collected, sorted by start timestamp, then
        grouped into consecutive speaker turns.
        """
        all_words: list[dict] = []

        for transcript in response.transcripts:
            channel = transcript.channel_index
            speaker_id = f"speaker_{channel}"
            for word in transcript.words or []:
                if hasattr(word, "type") and word.type != "word":
                    continue
                all_words.append({
                    "text": word.text,
                    "start": getattr(word, "start", 0.0),
                    "speaker": speaker_id,
                })

        if not all_words:
            # No word timestamps — fall back to concatenating channel texts
            return " ".join(
                t.text for t in response.transcripts if t.text
            ).strip()

        all_words.sort(key=lambda w: w["start"])

        # Group consecutive words that share the same speaker
        segments: list[tuple[str, str]] = []
        current_speaker: str | None = None
        current_words: list[str] = []

        for w in all_words:
            if w["speaker"] != current_speaker:
                if current_words:
                    segments.append((current_speaker, " ".join(current_words)))
                current_speaker = w["speaker"]
                current_words = [w["text"]]
            else:
                current_words.append(w["text"])

        if current_words:
            segments.append((current_speaker, " ".join(current_words)))

        return "\n\n".join(f"[{speaker}]: {text}" for speaker, text in segments)
