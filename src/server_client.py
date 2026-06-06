# server_client.py — Raspberry Pi 3 Bus Node
# Handles all HTTP communication with the City Hall server.
# Offline queue writes each event as a JSON file on the SD card immediately —
# events survive Pi power loss and are loaded back on next boot.

import json
import os
import logging
import time
from datetime import datetime
from pathlib import Path
from threading import Thread, Event, Lock
from typing import Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import SERVER_CONFIG, OFFLINE_CONFIG, HEARTBEAT_CONFIG

logger = logging.getLogger(__name__)


def _build_session() -> requests.Session:
    session = requests.Session()
    retry   = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.headers.update({
        'X-API-Key':    SERVER_CONFIG['api_key'],
        'Content-Type': 'application/json',
    })
    return session


_session = _build_session()


class OfflineQueue:
    """
    Disk-backed offline event queue.
    Every event is written to an individual JSON file in offline_data/ immediately
    so that Pi power loss does not discard queued events.
    On startup, any existing files are loaded back into the send queue.
    """

    def __init__(self):
        self._dir = Path(OFFLINE_CONFIG['data_dir'])
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock    = Lock()
        self._pending: List[Dict] = []
        self._load_from_disk()

    def _load_from_disk(self):
        files = sorted(self._dir.glob('*.json'))
        loaded = 0
        for fpath in files:
            try:
                with open(fpath) as f:
                    event = json.load(f)
                event['_file'] = str(fpath)
                self._pending.append(event)
                loaded += 1
            except Exception as e:
                logger.warning(f"Could not load offline file {fpath.name}: {e}")
                try:
                    fpath.unlink()
                except Exception:
                    pass
        if loaded:
            logger.info(f"Offline queue: loaded {loaded} events from disk.")

    def put(self, event: Dict):
        """Persist event to disk and add to send queue."""
        # Build a safe filename from timestamp and bus_id
        ts     = event.get('timestamp', datetime.utcnow().isoformat())
        bus_id = str(event.get('bus_id', 'unknown')).replace(':', '')
        safe_ts = ts.replace(':', '-').replace('.', '-')[:23]
        fname  = self._dir / f"{safe_ts}__{bus_id}.json"
        try:
            with open(fname, 'w') as f:
                json.dump(event, f)
        except Exception as e:
            logger.error(f"Could not persist offline event: {e}")
            fname = None

        with self._lock:
            entry = dict(event)
            if fname:
                entry['_file'] = str(fname)
            self._pending.append(entry)

        max_q = OFFLINE_CONFIG.get('max_queued_events', 500)
        with self._lock:
            if len(self._pending) > max_q:
                dropped = self._pending.pop(0)
                f = dropped.get('_file')
                if f:
                    try:
                        Path(f).unlink()
                    except Exception:
                        pass
                logger.warning("Offline queue full — oldest event dropped.")

    def flush(self, endpoint: str) -> int:
        """Attempt to send all pending events. Returns count sent."""
        with self._lock:
            to_send = list(self._pending)

        sent = 0
        still_pending = []
        for entry in to_send:
            fpath = entry.pop('_file', None)
            payload = {k: v for k, v in entry.items()}
            try:
                r = _session.post(endpoint, json=payload,
                                  timeout=SERVER_CONFIG['timeout'])
                r.raise_for_status()
                sent += 1
                if fpath:
                    try:
                        Path(fpath).unlink()
                    except Exception:
                        pass
            except Exception:
                entry['_file'] = fpath
                still_pending.append(entry)
                break  # Server still unreachable — stop trying

        with self._lock:
            sent_set = set(id(e) for e in to_send) - set(id(e) for e in still_pending)
            self._pending = still_pending + [
                e for e in self._pending if id(e) not in sent_set
            ]

        if sent:
            logger.info(f"Offline queue: flushed {sent} events.")
        return sent

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._pending)


_offline_queue = OfflineQueue()


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_routes(region: str) -> Optional[List[Dict]]:
    url = f"{SERVER_CONFIG['base_url']}/api/routes?region={region}"
    try:
        r = _session.get(url, timeout=SERVER_CONFIG['timeout'])
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"Could not fetch routes: {e}")
        return None


def post_stop_event(event: Dict) -> bool:
    url = f"{SERVER_CONFIG['base_url']}/api/bus/stop"
    try:
        r = _session.post(url, json=event, timeout=SERVER_CONFIG['timeout'])
        r.raise_for_status()
        if _offline_queue.size > 0:
            _offline_queue.flush(url)
        return True
    except Exception as e:
        logger.warning(f"Server unreachable, queuing event: {e}")
        _offline_queue.put(event)
        return False


def post_heartbeat(payload: Dict) -> bool:
    url = f"{SERVER_CONFIG['base_url']}/api/bus/heartbeat"
    try:
        r = _session.post(url, json=payload, timeout=SERVER_CONFIG['timeout'])
        r.raise_for_status()
        return True
    except Exception:
        return False


def register_bus(bus_id: str, region: str) -> bool:
    url = f"{SERVER_CONFIG['base_url']}/api/bus/register"
    try:
        r = _session.post(url, json={'bus_id': bus_id, 'region': region},
                          timeout=SERVER_CONFIG['timeout'])
        r.raise_for_status()
        logger.info(f"Bus {bus_id} registered.")
        return True
    except Exception as e:
        logger.warning(f"Could not register bus: {e}")
        return False


class HeartbeatService:
    def __init__(self):
        self._payload: Dict = {}
        self._lock   = Lock()
        self._stop   = Event()
        self._thread = Thread(target=self._loop, daemon=True, name='heartbeat')

    def start(self):
        self._thread.start()
        logger.info("Heartbeat service started.")

    def stop(self):
        self._stop.set()

    def update_position(self, bus_id: str, route_id: str,
                        stop_name: str, lat: float, lng: float, direction: str):
        with self._lock:
            self._payload = {
                'bus_id':    bus_id,
                'route_id':  route_id,
                'stop_name': stop_name,
                'lat':       lat,
                'lng':       lng,
                'direction': direction,
                'timestamp': datetime.utcnow().isoformat() + 'Z',
            }

    def _loop(self):
        interval = HEARTBEAT_CONFIG['interval_seconds']
        while not self._stop.wait(interval):
            with self._lock:
                payload = dict(self._payload)
            if payload:
                post_heartbeat(payload)
