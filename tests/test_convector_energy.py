"""Regression tests based on anonymized legacy convector responses."""

from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from ioteldom.crc import crc32
from ioteldom.energy import ConvectorEnergyClient, parse_energy_record


def response(timestamp=1793318400, total=103):
    data = {f"P{hour}": "0" for hour in range(24)}
    for hour, value in enumerate((16, 18, 16, 14, 12, 10, 11, 6), 8):
        data[f"P{hour}"] = str(value)
    return dict(data, Date=str(timestamp), TotalPower=str(total))


class EnergyRecordTests(unittest.TestCase):
    def test_live_response_and_numeric_hour_order(self):
        # Deliberately reverse JSON field order: P10 must not precede P2.
        record = parse_energy_record(dict(reversed(list(response().items()))), 2)
        self.assertEqual(record.date, date(2026, 10, 30))
        self.assertEqual(record.total_energy, 6.87)
        for actual, counter in zip(record.hourly_energy[8:16],
                                   (16, 18, 16, 14, 12, 10, 11, 6)):
            self.assertAlmostEqual(actual, counter * 0.06666)
        self.assertEqual(round(sum(record.hourly_energy), 2), record.total_energy)

    def test_all_power_classes(self):
        for power_class, expected in enumerate((3.33, 5.0, 6.67, 8.33, 10.0)):
            self.assertEqual(parse_energy_record(response(total=100), power_class).total_energy,
                             expected)

    def test_zero_is_valid(self):
        self.assertEqual(parse_energy_record(response(total=0), 2).total_energy, 0)

    def test_invalid_values_are_not_reported_as_zero(self):
        for key, value in (("TotalPower", "nan"), ("P2", "-1"),
                           ("Date", "0"), ("Date", "inf")):
            data = response()
            data[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                parse_energy_record(data, 2)
        with self.assertRaises(ValueError):
            parse_energy_record(response(), 5)


class EnergyClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_late_record_duplicates_and_sorting(self):
        client = ConvectorEnergyClient(None, None)
        samples = [response(1775260800, 0)] * 5
        samples += [response(), response(1793145600, 6)] * 4
        samples += [response(total=104)]
        client._request = AsyncMock(side_effect=[{"SystemSettings": "1, 2, 2, 0"}] + samples)
        with patch("ioteldom.energy.asyncio.sleep", new_callable=AsyncMock) as sleep:
            records = await client.get_statistics(object())
        self.assertEqual(len(records), 3)
        self.assertEqual(records[-1].date, date(2026, 10, 30))
        self.assertEqual(records[-1].total_energy, 6.93)
        self.assertEqual(sleep.await_count, 13)
        self.assertEqual(client._request.await_count, 15)

    async def test_unknown_power_class_stops_before_statistics(self):
        client = ConvectorEnergyClient(None, None)
        client._request = AsyncMock(return_value={"SystemSettings": "1, 9, 2, 0"})
        with self.assertRaises(ValueError):
            await client.get_statistics(object())
        self.assertEqual(client._request.await_count, 1)

    async def test_request_authentication_and_checksum(self):
        reply = MagicMock()
        reply.json = AsyncMock(return_value=response())
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=reply)
        context.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post.return_value = context
        provider = SimpleNamespace(provide=AsyncMock(return_value="test-token"))
        device = SimpleNamespace(uuid="test-device", pairTok="test-pair")
        client = ConvectorEnergyClient(session, provider)
        await client._request(device, "GetEnergyStatistic")
        args, kwargs = session.post.call_args
        self.assertTrue(args[0].endswith("/api/direct-req"))
        payload = kwargs["json"].copy()
        checksum = payload.pop("CRC")
        self.assertEqual(checksum, crc32(payload))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-token")
        self.assertEqual(kwargs["headers"]["ionic-idd"], "test-device")


if __name__ == "__main__":
    unittest.main()
