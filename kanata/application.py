from dataclasses import dataclass

from .device import Hidraw, Session
from .protocol import Settings
from .reports import ProtocolError


@dataclass(frozen=True)
class DeviceState:
    settings: Settings
    identity: dict
    battery: dict | None = None
    node: str | None = None
    message: str = ''


class DeviceService:
    def __init__(self, transport_factory=Hidraw):
        self.transport_factory = transport_factory

    def read(self, node: str, trace: list) -> DeviceState:
        with self.transport_factory(node, trace) as transport:
            session = Session(transport)
            identity = session.identify()
            settings = session.read_settings(include_macros=True)
            try:
                battery = session.battery()
            except ProtocolError:

                battery = None
            return DeviceState(settings, identity, battery, node)

    def apply(self, node: str, trace: list, baseline: Settings, draft: tuple,
              battery: dict | None) -> DeviceState:
        with self.transport_factory(node, trace) as transport:
            session = Session(transport)
            identity = session.identify()
            settings, count = session.apply(baseline, *draft)
            return DeviceState(
                settings, identity, battery, node,
                f"Applied {count} records; each passed a device readback check.",
            )
