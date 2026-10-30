"""Read the legacy convector's dated, estimated energy records."""

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone
import math

import aiohttp

from .constants import BASE_URL
from .crc import crc32


# Preserve the legacy application's conversion, including its rounding factors.
POWER_CLASS_FACTORS = (0.03333, 0.05, 0.06666, 0.08333, 0.1)


@dataclass(frozen=True)
class ConvectorEnergyRecord:
    """A device calendar day and estimated consumption in kWh.

    Date is encoded as midnight UTC by the device. Treat it as a date label,
    rather than shifting it into the consumer's timezone. Hourly values are
    indexed P0 through P23; the protocol does not establish their timezone.
    """

    date: date
    total_energy: float
    hourly_energy: tuple


def parse_energy_record(response, power_class):
    """Validate and convert a statistics response without integer truncation."""
    if not 0 <= power_class < len(POWER_CLASS_FACTORS):
        raise ValueError("Unsupported convector power class")
    factor = POWER_CLASS_FACTORS[power_class]
    timestamp = float(response["Date"])
    if not math.isfinite(timestamp) or timestamp <= 0:
        raise ValueError("Invalid energy record date")
    values = [float(response["TotalPower"])]
    values.extend(float(response[f"P{hour}"]) for hour in range(24))
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("Invalid energy consumption counter")
    # Keep interval precision: rounding each hour before accumulating can drift
    # from the daily total. Only the displayed daily value follows app rounding.
    converted = [value * factor for value in values]
    return ConvectorEnergyRecord(
        datetime.fromtimestamp(timestamp, timezone.utc).date(),
        round(converted[0], 2),
        tuple(converted[1:]),
    )


class ConvectorEnergyClient:
    """Read-only energy commands using the existing authenticated session."""

    def __init__(self, session, token_provider):
        self.session = session
        self.token_provider = token_provider
        self._lock = asyncio.Lock()

    async def _request(self, device, command):
        payload = {"ID": device.pairTok, "Req": command, "CID": "1"}
        payload["CRC"] = crc32(payload)
        headers = {
            "ionic-idd": device.uuid,
            "Authorization": f"Bearer {await self.token_provider.provide()}",
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
        }
        async with self.session.post(
            f"{BASE_URL}/api/direct-req",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=45),
        ) as response:
            response.raise_for_status()
            result = await response.json(content_type=None)
        if not isinstance(result, dict) or "Msg" in result:
            raise ValueError("Unexpected legacy convector response")
        return result

    async def get_statistics(self, device):
        """Collect up to 14 responses, retaining the latest sample per date.

        The app sends seven identical requests. Live testing required spaced
        requests and returned duplicates before all seven distinct dates had
        appeared. Do not stop on the first duplicate or assume response order.
        This takes at least 26 seconds; callers should poll independently of
        climate status, at a substantially slower interval.
        """
        async with self._lock:
            params = await self._request(device, "GetParams")
            try:
                power_class = int(params["SystemSettings"].split(",")[1].strip())
            except (KeyError, IndexError, AttributeError, ValueError) as err:
                raise ValueError("Missing or invalid convector power class") from err
            if not 0 <= power_class < len(POWER_CLASS_FACTORS):
                raise ValueError("Unsupported convector power class")
            records = {}
            for index in range(14):
                if index:
                    await asyncio.sleep(2)
                record = parse_energy_record(
                    await self._request(device, "GetEnergyStatistic"), power_class
                )
                records[record.date] = record
            return sorted(records.values(), key=lambda record: record.date)
