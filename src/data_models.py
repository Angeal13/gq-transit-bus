# data_models.py  — Raspberry Pi 3 Bus Node
from dataclasses import dataclass, field
from typing import List, Optional
import uuid


@dataclass
class StopInfo:
    """A single bus stop with name and coordinates."""
    name: str
    lat:  float = 0.0
    lng:  float = 0.0


@dataclass
class BusRoute:
    id:         str
    stops:      List[StopInfo]   # ordered list of StopInfo objects
    route_type: int              # 1 = circular, 2 = bidirectional
    client:     str
    region:     str
    language:   str
    timezone:   str

    @property
    def stop_names(self) -> List[str]:
        return [s.name for s in self.stops]


class Bus:
    __slots__ = ['id', 'route', 'current_stop_index', 'direction', 'system_id']

    def __init__(self, bus_id: str, route: BusRoute):
        self.id                 = bus_id
        self.route              = route
        self.current_stop_index = 0
        self.direction          = 1
        self.system_id          = str(uuid.getnode())

    def set_direction(self, direction_choice: int):
        if direction_choice == 1 and self.route.route_type == 2:
            self.route.stops.reverse()
            self.direction = -1
        else:
            self.direction = 1

    def advance(self):
        """Move bus to the next stop (called after operator presses button)."""
        if self.route.route_type == 1:
            self.current_stop_index = (self.current_stop_index + 1) % len(self.route.stops)
        else:
            if self.direction == 1:
                if self.current_stop_index == len(self.route.stops) - 1:
                    self.direction = -1
                    self.current_stop_index -= 1
                else:
                    self.current_stop_index += 1
            else:
                if self.current_stop_index == 0:
                    self.direction = 1
                    self.current_stop_index += 1
                else:
                    self.current_stop_index -= 1

    @property
    def next_stop(self) -> Optional['StopInfo']:
        """Return the NEXT stop after current without advancing the index.

        Used by record_stop() to tell the server where the bus is heading so
        the map can display EN_TRANSITO immediately after button press.
        Returns None if the bus is at the last stop of a one-way route.
        """
        stops = self.route.stops
        n     = len(stops)
        idx   = self.current_stop_index
        if self.route.route_type == 1:
            return stops[(idx + 1) % n]
        else:
            if self.direction == 1:
                return stops[idx + 1] if idx < n - 1 else None
            else:
                return stops[idx - 1] if idx > 0 else None

    @property
    def current_stop(self) -> StopInfo:
        return self.route.stops[self.current_stop_index]

    @property
    def current_stop_name(self) -> str:
        return self.current_stop.name

    @property
    def current_lat(self) -> float:
        return self.current_stop.lat

    @property
    def current_lng(self) -> float:
        return self.current_stop.lng

    @property
    def final_destination(self) -> str:
        return self.route.stops[-1].name if self.direction == 1 else self.route.stops[0].name
