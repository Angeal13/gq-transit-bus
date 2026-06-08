# audio_system.py  — Raspberry Pi 3 Bus Node
# Offline-only TTS using pyttsx3 + espeak-ng (Spanish voice).
# No internet required at runtime. Voice data installed once during setup.

import pyttsx3
import time
import logging
from threading import Event

logger = logging.getLogger(__name__)

# espeak-ng language codes used by pyttsx3 on Linux
LANG_CODES = {
    'es': 'es',      # Spanish (default)
    'fr': 'fr',      # French
    'en': 'en',      # English
}

class AudioSystem:
    """Singleton audio engine backed entirely by pyttsx3 + espeak-ng.

    No network calls are made at any point. The espeak-ng voice data
    (Spanish, French, English) is downloaded once by install.sh and stored
    on the Pi. All announcements run from that local data.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._engines = {}   # one engine per language
            cls._instance._init_engines()
        return cls._instance

    def _init_engines(self):
        """Initialise one pyttsx3 engine per language with espeak-ng backend."""
        for lang_key, espeak_lang in LANG_CODES.items():
            try:
                engine = pyttsx3.init(driverName='espeak')
                engine.setProperty('rate', 130)       # slightly slower — clearer in a moving bus
                engine.setProperty('volume', 1.0)

                # Select espeak-ng voice by language code
                voices = engine.getProperty('voices')
                matched = [v for v in voices if espeak_lang in v.id.lower()]
                if matched:
                    engine.setProperty('voice', matched[0].id)
                    logger.info(f"Audio: language '{lang_key}' → voice '{matched[0].id}'")
                else:
                    # Fallback: set espeak language directly via voice id pattern
                    engine.setProperty('voice', f'espeak+{espeak_lang}')
                    logger.warning(f"Audio: no voice object for '{lang_key}', using id fallback.")

                self._engines[lang_key] = engine
            except Exception as e:
                logger.error(f"Audio: failed to init engine for '{lang_key}': {e}")

        if not self._engines:
            raise RuntimeError("Audio system: no pyttsx3 engines could be initialised.")

    def _get_engine(self, language: str) -> pyttsx3.Engine:
        """Return the engine for the requested language, falling back to Spanish."""
        return self._engines.get(language, self._engines.get('es'))

    def play_audio(self, text: str, language: str, exit_event: Event, repetitions: int = 1):
        """Speak *text* in *language* up to *repetitions* times.

        Blocks until playback is complete or exit_event is set.
        Between repetitions a 10-second gap is observed (bus stop dwell time).
        """
        engine = self._get_engine(language)
        if engine is None:
            logger.error("Audio: no engine available — announcement skipped.")
            return

        for i in range(repetitions):
            if exit_event.is_set():
                break
            try:
                engine.say(text)
                engine.runAndWait()
                logger.info(f"Audio: played [{language}] '{text[:60]}' (rep {i+1}/{repetitions})")
            except Exception as e:
                logger.error(f"Audio: playback error on rep {i+1}: {e}")
                break

            # Gap between repetitions — bus may announce a stop twice
            if i < repetitions - 1 and not exit_event.is_set():
                exit_event.wait(timeout=10)

    def cleanup(self):
        """Stop all engines gracefully on shutdown."""
        for lang, engine in self._engines.items():
            try:
                engine.stop()
            except Exception as e:
                logger.warning(f"Audio cleanup error for '{lang}': {e}")
        self._engines.clear()
        logger.info("Audio system shut down.")
