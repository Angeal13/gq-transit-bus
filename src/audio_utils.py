# audio_utils.py  — Raspberry Pi 3 Bus Node
import subprocess
import logging

logger = logging.getLogger(__name__)


class AudioConfig:

    @staticmethod
    def ensure_audio_output_jack():
        """Force audio to 3.5 mm jack and set volume to 80 %."""
        try:
            r = subprocess.run(['amixer', 'cset', 'numid=3', '1'],
                               capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                logger.warning(f"Set audio output failed: {r.stderr}")
                return False
            r = subprocess.run(['amixer', 'set', 'Master', '80%'],
                               capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                logger.warning(f"Set volume failed: {r.stderr}")
                return False
            logger.info("Audio: 3.5 mm jack at 80 %.")
            return True
        except subprocess.TimeoutExpired:
            logger.warning("Audio config timed out.")
            return False
        except Exception as e:
            logger.error(f"Audio config error: {e}")
            return False

    @staticmethod
    def test_audio_output():
        try:
            r = subprocess.run(['amixer', 'get', 'Master'],
                               capture_output=True, text=True, timeout=5)
            ok = r.returncode == 0 and '80%' in r.stdout
            if ok:
                logger.info("Audio output verified.")
            return ok
        except Exception as e:
            logger.warning(f"Audio test failed: {e}")
            return False

    @staticmethod
    def get_audio_status() -> str:
        try:
            r = subprocess.run(['amixer', 'cget', 'numid=3'],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                if 'values=1' in r.stdout:
                    return '3.5mm jack'
                elif 'values=2' in r.stdout:
                    return 'HDMI'
                return f'Unknown: {r.stdout}'
            return 'Error'
        except Exception as e:
            return f'Error: {e}'
