# controller.py — Raspberry Pi 3 Bus Node
# Keyboard: main keys [0]=next stop  [.]=emergency  [/]=complete route
# GPIO:     GPIO17=next stop  GPIO27=emergency  GPIO22=complete route

import keyboard
import sys
import time
import subprocess
import logging
from threading import Event, Thread

logger = logging.getLogger(__name__)


class StationController:

    def __init__(self):
        self.advance_event        = Event()
        self.exit_event           = Event()
        self.complete_route_event = Event()
        self._button_states       = {'advance': False, 'exit': False, 'complete': False}
        self.is_windows           = sys.platform.startswith('win')

        self._setup_keyboard()
        if not self.is_windows:
            self._setup_gpio_buttons()

    def _setup_keyboard(self):
        keyboard.add_hotkey('0', self.request_advance)
        keyboard.add_hotkey('.', self.request_exit)
        keyboard.add_hotkey('/', self.request_complete_route)
        logger.info("Keyboard: [0]=next stop  [.]=emergency  [/]=complete route")

    def _setup_gpio_buttons(self):
        try:
            import RPi.GPIO as GPIO
            from config import GPIO_CONFIG
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            self.advance_pin  = GPIO_CONFIG['advance_pin']
            self.exit_pin     = GPIO_CONFIG['exit_pin']
            self.complete_pin = GPIO_CONFIG['complete_pin']
            bt = GPIO_CONFIG['bouncetime_ms']
            for pin in (self.advance_pin, self.exit_pin, self.complete_pin):
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(self.advance_pin,  GPIO.FALLING,
                                  callback=self._advance_cb,  bouncetime=bt)
            GPIO.add_event_detect(self.exit_pin,     GPIO.FALLING,
                                  callback=self._exit_cb,     bouncetime=bt)
            GPIO.add_event_detect(self.complete_pin, GPIO.FALLING,
                                  callback=self._complete_cb, bouncetime=bt)
            Thread(target=self._monitor_buttons, daemon=True).start()
            logger.info(f"GPIO: advance=GPIO{self.advance_pin}  "
                        f"exit=GPIO{self.exit_pin}  complete=GPIO{self.complete_pin}")
        except ImportError:
            logger.warning("RPi.GPIO not available — keyboard only.")
        except Exception as e:
            logger.error(f"GPIO setup error: {e}")

    def _advance_cb(self, channel):
        if not self._button_states['advance']:
            self._button_states['advance'] = True
            self.request_advance()
            self._beep()

    def _exit_cb(self, channel):
        if not self._button_states['exit']:
            self._button_states['exit'] = True
            self.request_exit()
            self._beep()

    def _complete_cb(self, channel):
        if not self._button_states['complete']:
            self._button_states['complete'] = True
            self.request_complete_route()
            self._beep()

    def _monitor_buttons(self):
        while True:
            time.sleep(0.5)
            for k in self._button_states:
                self._button_states[k] = False

    def _beep(self):
        try:
            subprocess.run(['echo', '-e', '\a'], shell=False)
        except Exception:
            pass

    def request_advance(self):        self.advance_event.set()
    def request_exit(self):           self.exit_event.set()
    def request_complete_route(self): self.complete_route_event.set()

    def cleanup(self):
        keyboard.unhook_all()
        if not self.is_windows:
            try:
                import RPi.GPIO as GPIO
                GPIO.cleanup()
            except Exception:
                pass
        logger.info("Controller cleanup done.")
