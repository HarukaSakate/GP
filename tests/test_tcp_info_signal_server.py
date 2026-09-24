import importlib.util
import socket
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "tcp_info_signal_server.py"
SPEC = importlib.util.spec_from_file_location("tcp_info_signal_server", MODULE_PATH)
server = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = server
SPEC.loader.exec_module(server)


class FakeSocket:
    def __init__(self, value=b"cubic\x00"):
        self.value = value

    def getsockopt(self, level, option, length):
        self.last_call = (level, option, length)
        return self.value


def make_state(initialized=False):
    return server.ConnectionState(
        conn_id="127.0.0.1:50000->8000:test",
        client_ip="127.0.0.1",
        client_port=50000,
        server_port=8000,
        sock=FakeSocket(),
        opened_at=1.0,
        last_seen_at=1.0,
        initialized=initialized,
    )


def make_info():
    info = server.TcpInfo()
    info.tcpi_rtt = 20_000
    info.tcpi_min_rtt = 15_000
    info.tcpi_snd_cwnd = 24
    info.tcpi_snd_mss = 1_448
    info.tcpi_unacked = 12
    info.tcpi_total_retrans = 100
    info.tcpi_bytes_acked = 1_000_000
    info.tcpi_segs_out = 1_000
    info.tcpi_delivery_rate = 200_000
    info.tcpi_pacing_rate = 300_000
    info.tcpi_delivery_rate_app_limited = 1
    return info


class NormalizeSnapshotTests(unittest.TestCase):
    def test_first_sample_does_not_report_historical_counters_as_deltas(self):
        state = make_state(initialized=False)
        snapshot, *_ = server.normalize_snapshot(
            state, make_info(), "cubic", 0.5, "session-1", sampled_at=10.0
        )
        self.assertEqual(snapshot["retransmissions_delta"], 0)
        self.assertEqual(snapshot["retransmission_rate"], 0)
        self.assertEqual(snapshot["connection_id"], state.conn_id)
        self.assertEqual(snapshot["pacing_rate_bps"], 2_400_000)
        self.assertTrue(snapshot["app_limited"])

    def test_subsequent_sample_uses_counter_deltas(self):
        state = make_state(initialized=True)
        state.total_retrans_last = 98
        state.bytes_acked_last = 900_000
        state.segs_out_last = 900
        state.rtt_min_us = 10_000
        info = make_info()
        info.tcpi_delivery_rate = 0

        snapshot, *_ = server.normalize_snapshot(
            state, info, "cubic", 0.5, "session-1", sampled_at=10.0
        )
        self.assertEqual(snapshot["retransmissions_delta"], 2)
        self.assertAlmostEqual(snapshot["retransmission_rate"], 0.02)
        self.assertEqual(snapshot["delivery_rate_bps"], 1_600_000)
        self.assertEqual(snapshot["rtt_min_us"], 10_000)

    def test_counter_reset_is_clamped(self):
        state = make_state(initialized=True)
        state.total_retrans_last = 200
        state.bytes_acked_last = 2_000_000
        state.segs_out_last = 2_000
        snapshot, *_ = server.normalize_snapshot(
            state, make_info(), "cubic", 0.5, "session-1", sampled_at=10.0
        )
        self.assertEqual(snapshot["retransmissions_delta"], 0)
        self.assertEqual(snapshot["retransmission_rate"], 0)


class CongestionControlTests(unittest.TestCase):
    def test_reads_algorithm_from_socket(self):
        sock = FakeSocket(b"bbr\x00")
        self.assertEqual(server.read_congestion_control(sock), "bbr")
        self.assertEqual(sock.last_call[0], socket.IPPROTO_TCP)


class EbpfSelectionTests(unittest.TestCase):
    def test_selects_newest_matching_http_socket(self):
        session = server.SessionState("s1", "10.0.0.2", FakeSocket(), 1.0)
        def entry(remote_ip, local_port, timestamp_ns, cookie):
            return {
                "key": {"remote_ip": remote_ip, "local_port": local_port, "socket_cookie": cookie},
                "value": {"timestamp_ns": timestamp_ns},
            }
        entries = [
            entry("10.0.0.2", 8765, 999, 1),
            entry("10.0.0.3", 8000, 999, 2),
            entry("10.0.0.2", 8000, 100, 3),
            entry("10.0.0.2", 8000, 200, 4),
        ]
        selected = server.select_ebpf_entry_for_session(entries, session, 8000)
        self.assertEqual(selected["key"]["socket_cookie"], 4)

    def test_returns_none_without_matching_socket(self):
        session = server.SessionState("s1", "10.0.0.2", FakeSocket(), 1.0)
        self.assertIsNone(server.select_ebpf_entry_for_session([], session, 8000))


if __name__ == "__main__":
    unittest.main()
