# main_with_engine.py  — Raspberry Pi 3 Bus Node
# Drop-in replacement for main.py that adds engine health monitoring.
# Only new lines are marked with  # ENGINE HEALTH

import sys
import time
import logging
import keyboard
import uuid
from threading import Event
from datetime import datetime

from config import REGION_NAME, SERVER_CONFIG
from data_models import Bus, BusRoute
from audio_system import AudioSystem
from audio_utils import AudioConfig
from controller import StationController
from logic import StopTracker, RouteCache, RouteResumeService
from server_client import register_bus, HeartbeatService
from engine_health import EngineHealthService                    # ENGINE HEALTH

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/bus_node.log', mode='a'),
    ]
)
logger = logging.getLogger(__name__)


def _get_bus_id() -> str:
    try:
        mac = ':'.join([f'{(uuid.getnode() >> e) & 0xff:02x}'
                        for e in range(0, 48, 8)][::-1])
        return f"bus_{mac}"
    except Exception:
        return f"bus_{str(uuid.uuid4())[:8]}"


class BusTrackingSystem:

    def __init__(self):
        self.bus_id      = _get_bus_id()
        self.controller  = StationController()
        self.audio       = AudioSystem()
        self.route_cache = RouteCache()
        self.heartbeat   = HeartbeatService()
        self.active_bus  = None
        self._configure_audio()

        # ── Engine health service ─────────────────────────────  ENGINE HEALTH
        self.engine = EngineHealthService(
            bus_id     = self.bus_id,
            server_url = SERVER_CONFIG['base_url'],
            api_key    = SERVER_CONFIG['api_key'],
            audio_system = self.audio,
        )
        # ─────────────────────────────────────────────────────────────────────

    def _configure_audio(self):
        if AudioConfig.ensure_audio_output_jack():
            logger.info("Audio: 3.5 mm jack ready.")
        else:
            logger.warning("Audio config may need manual check.")

    def initialize(self):
        logger.info("=" * 60)
        logger.info(f"BUS NODE  |  ID: {self.bus_id}  |  Region: {REGION_NAME}")
        logger.info("=" * 60)

        register_bus(self.bus_id, REGION_NAME)
        self.heartbeat.start()
        self.engine.start()                                      # ENGINE HEALTH

        routes = self.route_cache.get_routes()
        if not routes:
            raise RuntimeError(
                f"No routes for {REGION_NAME}. Check server connection.")

        logger.info(f"Routes loaded: {len(routes)}")
        for rid, r in routes.items():
            logger.info(f"  {rid}: {r.stops[0].name} → {r.stops[-1].name}")

        resume_svc = RouteResumeService(self.bus_id)
        if resume_svc.exists():
            print("\nResume previous route? Press [/] within 5 seconds...")
            start = time.time()
            while time.time() - start < 5:
                if keyboard.is_pressed('/'):
                    bus = resume_svc.load(routes)
                    if bus:
                        self.active_bus = bus
                        tracker = StopTracker(bus, self.heartbeat)
                        msg = f"Resumiendo ruta {bus.id} en {bus.current_stop_name}"
                        logger.info(msg)
                        self.audio.play_audio(
                            msg, bus.route.language, Event(), repetitions=1)
                        return {'__RESUME__': tracker}
                time.sleep(0.1)

        return routes

    def run(self, routes):
        if isinstance(routes, dict) and '__RESUME__' in routes:
            self._operation_loop(routes['__RESUME__'], is_resume=True)
            return

        while True:
            try:
                route_id = input("\nEnter Route ID (or 'q' to quit): ").strip()
                if route_id.lower() == 'q':
                    break
                if route_id not in routes:
                    print("Invalid Route ID.")
                    continue

                route = routes[route_id]
                bus   = Bus(route_id, route)
                self.active_bus = bus

                print(f"\nStarting route {route_id}:")
                print(f"  [0] Forward — {route.stops[0].name}")
                if route.route_type == 2:
                    print(f"  [1] Reverse — {route.stops[-1].name}")

                choice = input("Direction (0/1): ").strip()
                bus.set_direction(int(choice) if choice in ('0', '1') else 0)

                tracker = StopTracker(bus, self.heartbeat)
                tracker.record_stop()
                tracker.announce_stop(self.audio, self.controller.exit_event)
                self._operation_loop(tracker)

            except Exception as e:
                logger.error(f"Loop error: {e}")
                time.sleep(3)

    def _operation_loop(self, tracker: StopTracker, is_resume=False):
        print("\n[0] Next stop   [.] Emergency stop   [/] Complete route")
        if is_resume:
            print("Resuming from previous position...")

        while not self.controller.exit_event.is_set():
            self.controller.advance_event.clear()
            self.controller.complete_route_event.clear()

            while (not self.controller.advance_event.is_set() and
                   not self.controller.exit_event.is_set() and
                   not self.controller.complete_route_event.is_set()):
                time.sleep(0.1)

            if self.controller.exit_event.is_set():
                break

            if self.controller.complete_route_event.is_set():
                tracker.resume_service.clear()
                msg = f"Ruta {tracker.bus.id} completada."
                self.audio.play_audio(
                    msg, tracker.bus.route.language, Event(), repetitions=1)
                print("Route completed.")
                break

            tracker.bus.next_stop()
            tracker.record_stop()
            tracker.announce_stop(self.audio, self.controller.exit_event)

    def cleanup(self):
        self.engine.stop()                                       # ENGINE HEALTH
        self.heartbeat.stop()
        self.controller.cleanup()
        self.audio.cleanup()
        logger.info("Bus node shutdown complete.")


def main():
    system = BusTrackingSystem()
    try:
        routes = system.initialize()
        system.run(routes)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        system.audio.play_audio("Error crítico del sistema.", 'es', Event())
    finally:
        system.cleanup()


if __name__ == '__main__':
    main()
