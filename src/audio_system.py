# audio_system.py  — Raspberry Pi 3 Bus Node
import pygame
import pyttsx3
import io
from gtts import gTTS
from gtts.tts import gTTSError
import time
from threading import Event
import requests
import socket
import logging

logger = logging.getLogger(__name__)


class AudioSystem:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_audio()
            cls._instance._cache = {}
        return cls._instance

    def _init_audio(self):
        self.engine = pyttsx3.init()
        self.engine.setProperty('rate', 140)
        self.engine.setProperty('volume', 1.0)
        for voice in self.engine.getProperty('voices'):
            if 'spanish' in voice.name.lower():
                self.engine.setProperty('voice', voice.id)
                break
        pygame.mixer.init()
        logger.info("Audio system initialised.")

    def play_audio(self, text: str, language: str, exit_event: Event, repetitions: int = 1):
        try:
            self._play_with_gtts(text, language, exit_event, repetitions)
        except (gTTSError, requests.exceptions.ConnectionError, socket.timeout) as e:
            logger.warning(f"gTTS unavailable ({e}), falling back to pyttsx3.")
            self._play_with_pyttsx3(text, exit_event, repetitions)
        except Exception as e:
            logger.error(f"Audio error ({e}), falling back to pyttsx3.")
            self._play_with_pyttsx3(text, exit_event, repetitions)

    def _play_with_gtts(self, text: str, language: str, exit_event: Event, repetitions: int):
        key = (text, language)
        if key not in self._cache:
            tts = gTTS(text=text, lang=language)
            fp  = io.BytesIO()
            tts.write_to_fp(fp)
            self._cache[key] = fp.getvalue()

        audio_data = self._cache[key]
        for i in range(repetitions):
            if exit_event.is_set():
                break
            fp = io.BytesIO(audio_data)
            fp.seek(0)
            pygame.mixer.music.load(fp, 'mp3')
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy() and not exit_event.is_set():
                pygame.time.Clock().tick(10)
            if i < repetitions - 1 and not exit_event.is_set():
                time.sleep(10)

    def _play_with_pyttsx3(self, text: str, exit_event: Event, repetitions: int):
        for i in range(repetitions):
            if exit_event.is_set():
                break
            self.engine.say(text)
            if i < repetitions - 1:
                original_rate = self.engine.getProperty('rate')
                self.engine.setProperty('rate', 1)
                self.engine.say("   ")
                self.engine.setProperty('rate', original_rate)
        self.engine.runAndWait()

    def cleanup(self):
        pygame.mixer.quit()
        self.engine.stop()
