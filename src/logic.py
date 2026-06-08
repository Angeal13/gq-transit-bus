# logic.py  — Raspberry Pi 3 Bus Node
import json
import os
import pytz
import logging
from datetime import datetime
from typing import Dict, Optional

from data_models import Bus, BusRoute, StopInfo
from audio_system import AudioSystem
from server_client import post_stop_event, HeartbeatService, fetch_routes
from config import REGION_NAME, OFFLINE_CONFIG

logger = logging.getLogger(__name__)

ROUTES_CACHE_FILE = f'routes_cache_{REGION_NAME.lower()}.json'


# ─── Route cache ──────────────────────────────────────────────────────────────

class RouteCache:
    _instance  = None
    _routes    = None
    _last_load = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_routes(self, force_refresh=False) -> Dict[str, BusRoute]:
        age = (datetime.now() - self._last_load).total_seconds() if self._last_load else 9999
        if self._routes is None or force_refresh or age > 3600:
            self._load()
        return self._routes or {}

    def _load(self):
        # 1. Try server
        raw = fetch_routes(REGION_NAME)
        if raw:
            self._routes = self._parse(raw)
            self._save_cache(raw)
            self._last_load = datetime.now()
            logger.info(f"Loaded {len(self._routes)} routes from server.")
            return

        # 2. Fall back to local cache
        if os.path.exists(ROUTES_CACHE_FILE):
            try:
                with open(ROUTES_CACHE_FILE) as f:
                    raw = json.load(f)
                self._routes = self._parse(raw)
                self._last_load = datetime.now()
                logger.warning(f"Loaded {len(self._routes)} routes from LOCAL CACHE (server offline).")
                return
            except Exception as e:
                logger.error(f"Cache load failed: {e}")

        self._routes = {}
        logger.error("No routes available — server offline and no local cache.")

    @staticmethod
    def _parse(raw: list) -> Dict[str, BusRoute]:
        routes = {}
        for r in raw:
            stops = [StopInfo(name=s['name'], lat=s.get('lat', 0.0), lng=s.get('lng', 0.0))
                     for s in r['stops']]
            routes[r['id']] = BusRoute(
                id=r['id'], stops=stops, route_type=r['route_type'],
                client=r['client'], region=r['region'],
                language=r['language'], timezone=r['timezone']
            )
        return routes

    def _save_cache(self, raw: list):
        try:
            with open(ROUTES_CACHE_FILE, 'w') as f:
                json.dump(raw, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save route cache: {e}")


# ─── Resume service ───────────────────────────────────────────────────────────

class RouteResumeService:
    def __init__(self, bus_id: str):
        self.bus_id      = bus_id
        self.resume_file = f"route_resume_{bus_id.replace(' ', '_')}.json"

    def save(self, bus: Bus):
        data = {
            'bus_id':            bus.id,
            'route_id':          bus.route.id,
            'current_stop_index': bus.current_stop_index,
            'direction':         bus.direction,
            'timestamp':         datetime.now().isoformat(),
        }
        try:
            with open(self.resume_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"Resume save error: {e}")

    def load(self, routes: Dict[str, BusRoute]) -> Optional[Bus]:
        if not os.path.exists(self.resume_file):
            return None
        try:
            with open(self.resume_file) as f:
                data = json.load(f)
            route = routes.get(data['route_id'])
            if not route:
                return None
            bus = Bus(data['bus_id'], route)
            bus.current_stop_index = data['current_stop_index']
            bus.direction          = data['direction']
            logger.info(f"Resumed at stop {bus.current_stop_index}: {bus.current_stop_name}")
            return bus
        except Exception as e:
            logger.error(f"Resume load error: {e}")
            return None

    def clear(self):
        if os.path.exists(self.resume_file):
            os.remove(self.resume_file)
            logger.info("Resume point cleared.")

    def exists(self) -> bool:
        return os.path.exists(self.resume_file)


# ─── Stop tracker ─────────────────────────────────────────────────────────────

class StopTracker:
    _announcement_templates = {
        'es': "Ruta {route_id}, con dirección {direction}, Estación {stop_name}",
        'en': "Route {route_id}, direction {direction}, Stop {stop_name}",
        'fr': "Route {route_id}, direction {direction}, Station {stop_name}",
        'pt': "Percurso {route_id}, direção {direction}, Estação {stop_name}",
    }

    def __init__(self, bus: Bus, heartbeat_service: HeartbeatService):
        self.bus               = bus
        self.heartbeat_service = heartbeat_service
        self.resume_service    = RouteResumeService(bus.system_id)
        tz                     = bus.route.timezone
        self.tz                = pytz.timezone(tz)

    def record_stop(self):
        """Send stop event to server and update heartbeat position.

        Sends bus_status='AT_STOP' plus next stop coordinates so the server
        and Leaflet map can immediately switch to EN_TRANSITO state toward
        the next stop — simulating real-time GPS tracking between stops.
        """
        now       = datetime.now(self.tz)
        next_stop = self.bus.next_stop  # StopInfo or None at end of route

        event = {
            'bus_id':         self.bus.system_id,
            'route_id':       self.bus.id,
            'stop_name':      self.bus.current_stop_name,
            'lat':            self.bus.current_lat,
            'lng':            self.bus.current_lng,
            'direction':      self.bus.final_destination,
            'bus_status':     'AT_STOP',
            'next_stop_name': next_stop.name if next_stop else None,
            'next_lat':       next_stop.lat  if next_stop else None,
            'next_lng':       next_stop.lng  if next_stop else None,
            'client':         self.bus.route.client,
            'region':         self.bus.route.region,
            'language':       self.bus.route.language,
            'timezone':       self.bus.route.timezone,
            'timestamp':      now.isoformat(),
        }
        post_stop_event(event)
        self.heartbeat_service.update_position(
            bus_id         = self.bus.system_id,
            route_id       = self.bus.id,
            stop_name      = self.bus.current_stop_name,
            lat            = self.bus.current_lat,
            lng            = self.bus.current_lng,
            direction      = self.bus.final_destination,
            bus_status     = 'AT_STOP',
            next_stop_name = next_stop.name if next_stop else None,
            next_lat       = next_stop.lat  if next_stop else None,
            next_lng       = next_stop.lng  if next_stop else None,
        )
        self.resume_service.save(self.bus)
        logger.info(f"Stop recorded: {self.bus.current_stop_name} "
                    f"({self.bus.current_lat:.5f}, {self.bus.current_lng:.5f}) "
                    f"→ next: {next_stop.name if next_stop else 'END'}")

    def announce_stop(self, audio_system: AudioSystem, exit_event):
        lang     = self.bus.route.language or 'es'
        template = self._announcement_templates.get(lang, self._announcement_templates['es'])
        text     = template.format(
            route_id  = self.bus.id,
            direction = self.bus.final_destination,
            stop_name = self.bus.current_stop_name,
        )
        logger.info(f"Announcing: {text}")
        audio_system.play_audio(text, lang, exit_event, repetitions=3)
