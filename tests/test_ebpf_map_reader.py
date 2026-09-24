import importlib.util
import socket
import struct
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "ebpf_map_reader.py"
SPEC = importlib.util.spec_from_file_location("ebpf_map_reader", MODULE_PATH)
reader = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = reader
SPEC.loader.exec_module(reader)


class DecoderTests(unittest.TestCase):
    def test_ipv4_key_decoder(self):
        raw = bytearray(reader.KEY_STRUCT.size)
        struct.pack_into("<Q", raw, 0, 42)
        struct.pack_into("<I", raw, 8, socket.AF_INET)
        raw[12:16] = socket.inet_pton(socket.AF_INET, "10.0.0.1")
        raw[16:20] = socket.inet_pton(socket.AF_INET, "10.0.0.2")
        struct.pack_into("<II", raw, 52, 8000, 53124)
        decoded = reader.decode_key(bytes(raw))
        self.assertEqual(decoded["socket_cookie"], 42)
        self.assertEqual(decoded["local_ip"], "10.0.0.1")
        self.assertEqual(decoded["remote_ip"], "10.0.0.2")
        self.assertEqual(decoded["local_port"], 8000)

    def test_normalizer_computes_retransmission_delta(self):
        normalizer = reader.SnapshotNormalizer()
        entry = {
            "key": {"socket_cookie": 42, "local_ip": "10.0.0.1", "remote_ip": "10.0.0.2", "local_port": 8000, "remote_port": 53124},
            "value": {"rtt_us": 10000, "rtt_min_us": 8000, "cwnd_packets": 20, "packets_out": 10, "total_retrans": 5, "segs_out": 100, "delivery_rate_bps": 1000000, "pacing_rate_bps": 1200000, "app_limited": 0},
        }
        first = normalizer.normalize(entry, "s1", "cubic")
        self.assertEqual(first["retransmissions_delta"], 0)
        entry["value"]["total_retrans"] = 7
        entry["value"]["segs_out"] = 120
        second = normalizer.normalize(entry, "s1", "cubic")
        self.assertEqual(second["retransmissions_delta"], 2)
        self.assertAlmostEqual(second["retransmission_rate"], 0.1)


if __name__ == "__main__":
    unittest.main()
