"""Tests hors ligne : aucun périphérique ni API Windows réelle n'est ouvert."""
import contextlib
import ctypes
import io
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pc'))
import struct
import tempfile
import unittest
from unittest.mock import patch

import capture_usb as capture
import ddf350_hid as reader


def report(ch1=1023, ch2=1023):
    return b'\0\0' + struct.pack('<HH', ch1, ch2) + bytes(12)


class MetricsTests(unittest.TestCase):
    def test_20ms_and_1ms_frequency_and_bounded_storage(self):
        for step, count in ((20_000_000, 1001), (1_000_000, 20_001)):
            with self.subTest(step=step):
                metrics = capture.Metrics()
                original_size = len(metrics.histogram)
                for i in range(count):
                    metrics.add(report(), 10_000_000_000 + i * step)
                result = metrics.summary()
                self.assertEqual(result['reports_received'], count)
                self.assertEqual(result['frequency_hz'], 1e9 / step)
                self.assertEqual(result['intervals']['maximum_ms'], step / 1e6)
                for percentile in ('p50', 'p95', 'p99'):
                    value = result['intervals'][percentile]
                    self.assertLessEqual(value['lower_ms'], step / 1e6)
                    self.assertGreaterEqual(value['upper_ms'], step / 1e6)
                self.assertEqual(len(metrics.histogram), original_size)
                self.assertEqual(sum(metrics.histogram), count - 1)
                self.assertEqual(result['channel_changes']['unchanged_both'], count - 1)

    def test_nearest_rank_quantile_bounds_and_histogram(self):
        intervals = [1_000_123] * 50 + [2_000_456] * 45 + [20_123_456] * 4 + [1_500_000_000]
        metrics, timestamp = capture.Metrics(), 0
        metrics.add(report(), timestamp)
        for interval in intervals:
            timestamp += interval
            metrics.add(report(), timestamp)
        summary = metrics.summary()['intervals']
        for name, expected in (('p50', intervals[49]), ('p95', intervals[94]), ('p99', intervals[98])):
            self.assertLessEqual(summary[name]['lower_ms'], expected / 1e6)
            self.assertGreaterEqual(summary[name]['upper_ms'], expected / 1e6)
            self.assertLessEqual(summary[name]['upper_ms'] - summary[name]['lower_ms'], 0.01000001)
        self.assertEqual(sum(row['count'] for row in summary['histogram']), 100)
        self.assertEqual(summary['maximum_ms'], 1500)
        self.assertTrue(metrics.percentile(100)['overflow'])
        self.assertEqual(metrics.percentile(100)['upper_ms'], 1500)

    def test_invalid_raw_preserved_and_channel_deltas_across_invalid(self):
        metrics = capture.Metrics()
        metrics.add(report(1000, 1100), 0)
        invalid = metrics.add(b'\0\x01', 1)
        self.assertFalse(invalid['valid'])
        self.assertEqual(invalid['raw_hex'], '0001')
        row = metrics.add(report(1020, 1080), 2)
        self.assertEqual((row['delta_ch1'], row['delta_ch2'], row['previous_valid_seq']), (20, -20, 1))
        metrics.add(bytes([1]) + report()[1:], 3)
        metrics.add(report(2048, 1), 4)
        result = metrics.summary()
        self.assertEqual((result['valid_reports'], result['invalid_reports']), (2, 3))
        self.assertEqual(result['channel_changes']['channels']['ch2']['max_abs_step'], 20)

    def test_zero_intervals_and_nonmonotonic_fixture(self):
        metrics = capture.Metrics()
        self.assertIsNone(metrics.summary()['frequency_hz'])
        metrics.add(report(), 10)
        metrics.add(report(), 10)
        self.assertIsNone(metrics.summary()['frequency_hz'])
        self.assertEqual(metrics.summary()['intervals']['p50']['upper_ms'], 0)
        for invalid in (9, -1, True, 1.5, None):
            with self.assertRaises(ValueError):
                metrics.add(report(), invalid)
        self.assertEqual(metrics.reports, 2)


class LoggerTests(unittest.TestCase):
    def test_full_queue_explicit_losses_metrics_keep_every_reception(self):
        stream = io.StringIO()
        logger = capture.JsonlLogger(None, {}, capacity=2, stream=stream, autostart=False)
        sink = capture.Capture(logger)
        for i in range(5):
            sink.accept(report(i, i + 1), i * 1_000_000)
        self.assertEqual(logger.queue.qsize(), 2)
        summary = logger.finish(dict(capture=sink.metrics.summary()))
        self.assertEqual(summary['capture']['reports_received'], 5)
        self.assertEqual(summary['logging']['dropped_queue_full'], 3)
        self.assertEqual(summary['logging']['written'], 2)
        self.assertFalse(summary['logging']['complete'])
        rows = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual([row['seq'] for row in rows if row['type'] == 'report'], [1, 2])
        self.assertEqual(rows[-1]['logging']['dropped_queue_full'], 3)

    def test_io_failure_and_unwritten_count(self):
        class BrokenStream(io.StringIO):
            def write(self, value):
                if '"type":"report"' in value:
                    raise OSError('Disque simulé indisponible')
                return super().write(value)
        logger = capture.JsonlLogger(None, {}, capacity=3, stream=BrokenStream(), autostart=False)
        metrics = capture.Metrics()
        for i in range(3):
            logger.submit(metrics.add(report(), i))
        logger.start()
        self.assertTrue(logger.failed.wait(2))
        self.assertFalse(logger.submit(metrics.add(report(), 4)))
        summary = logger.finish({})['logging']
        self.assertEqual(summary['accepted_but_unwritten'], 3)
        self.assertEqual(summary['rejected_after_io_error'], 1)
        self.assertEqual(summary['written'], 0)
        self.assertIn('Disque simulé', summary['error'])

    def test_existing_output_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'capture.jsonl'
            path.write_text('original', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                capture.JsonlLogger(path, {})
            self.assertEqual(path.read_text(encoding='utf-8'), 'original')

    def test_streaming_many_reports_and_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'capture.jsonl'
            logger = capture.JsonlLogger(path, {'mode': 'fixture'}, capacity=16384)
            sink = capture.Capture(logger)
            for i in range(10_000):
                sink.accept(report(i % 2048, 1023), i * 1_000_000)
            result = logger.finish(dict(capture=sink.metrics.summary()))
            self.assertTrue(result['logging']['complete'])
            self.assertEqual(result['logging']['written'], 10_000)
            self.assertEqual(sum(1 for _ in capture.read_fixture(path)), 10_000)
            self.assertLessEqual(result['logging']['queue_high_water_observed'], 16384)


class FixtureTests(unittest.TestCase):
    def test_cli_fixture_no_hardware_and_footer(self):
        with tempfile.TemporaryDirectory() as folder:
            source, destination = Path(folder) / 'input.jsonl', Path(folder) / 'output.jsonl'
            source.write_text('\n'.join(json.dumps(dict(raw_hex=report(1000 + i).hex(), monotonic_ns=i * 20_000_000))
                                        for i in range(10)), encoding='utf-8')
            with patch.object(reader.WindowsHid, '__init__', side_effect=AssertionError('Accès matériel interdit')):
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    code = capture.main(['fixture', str(source), '--output', str(destination)])
            self.assertEqual(code, 0)
            result = json.loads(out.getvalue())
            self.assertEqual(result['capture']['frequency_hz'], 50)
            self.assertEqual(result['capture']['reports_received'], 10)
            self.assertEqual(result['logging']['written'], 10)
            self.assertIn('bout en bout', result['capture']['limitation'])

    def test_malformed_and_oversized_fixture_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'input.jsonl'
            for body in ('[]', '{"raw_hex": "' + '00' * 19 + '", "monotonic_ns":0}', ' ' * 65537):
                source.write_text(body, encoding='utf-8')
                with self.assertRaises(ValueError):
                    list(capture.read_fixture(source))


class NativeLifetimeTests(unittest.TestCase):
    def test_default_clock_is_high_resolution_and_metadata_identifies_it(self):
        with patch.object(capture.time, 'perf_counter_ns', return_value=123) as highres:
            with patch.object(capture.time, 'monotonic_ns', side_effect=AssertionError('Horloge grossière interdite')):
                worker = capture.CaptureWorker(None)
                self.assertIs(worker.clock_ns, highres)
                self.assertEqual(worker.clock_ns(), 123)
                metadata = capture.clock_metadata('live')
        self.assertEqual(metadata['clock'], 'time.perf_counter_ns')
        self.assertTrue(metadata['host_clock_info']['monotonic'])
        self.assertIn('resolution_seconds', metadata['host_clock_info'])

    def test_deadline_uses_exact_same_clock_as_worker(self):
        trace = []
        class FakeWorker:
            connected_ns = 100_000_000_000  # Domaine volontairement distinct de l'horloge système.
            finished_ns = 100_025_000_000
            version = 1
            error = None
            alive = True
            def __init__(self, sink):
                pass
            def start(self):
                pass
            def is_alive(self):
                return self.alive
            def clock_ns(self):
                trace.append('worker_clock')
                return 100_020_000_000
            def request_stop(self):
                trace.append('stop'); self.alive = False
            def join(self, timeout):
                if self.alive:
                    raise AssertionError('Echéance dans le mauvais domaine temporel')
        sink = type('Sink', (), {'logger': type('Logger', (), {'failed': threading_event()})})
        with patch.object(capture, 'CaptureWorker', FakeWorker):
            with patch.object(capture.time, 'monotonic_ns', side_effect=AssertionError('Horloge grossière interdite')):
                result = capture.run_live(sink, 0.02)
        self.assertEqual(trace, ['worker_clock', 'stop'])
        self.assertTrue(result['reader_stopped'])

    def test_reused_read_one_cancel_is_drained_before_return(self):
        # Adapter simulé : jamais WinDLL, handle, énumération ou ReadFile réel.
        worker = reader.Reader(None)
        trace = []
        class FakeApi:
            def ResetEvent(self, event):
                trace.append('reset'); return True
            def ReadFile(self, handle, buffer, size, unused, overlapped):
                self.overlapped = ctypes.addressof(overlapped._obj)
                trace.append('read')
                ctypes.set_last_error(reader.ERROR_IO_PENDING)
                return False
            def WaitForSingleObject(self, event, delay):
                trace.append('wait'); worker.stop_event.set(); return reader.WAIT_TIMEOUT
            def CancelIoEx(self, handle, overlapped):
                self.assert_same(overlapped); trace.append('cancel'); return True
            def GetOverlappedResult(self, handle, overlapped, received, wait):
                self.assert_same(overlapped)
                if not wait:
                    raise AssertionError('Annulation non vidangée')
                trace.append('drain'); return False
            def assert_same(self, overlapped):
                if ctypes.addressof(overlapped._obj) != self.overlapped:
                    raise AssertionError('OVERLAPPED différent')
        worker.api = FakeApi()
        with self.assertRaises(OSError) as failure:
            worker.read_one(11, 22)
        self.assertEqual(failure.exception.errno, reader.ERROR_OPERATION_ABORTED)
        self.assertEqual(trace, ['reset', 'read', 'wait', 'cancel', 'drain'])

    def test_worker_timestamp_before_decode_and_close_on_stop(self):
        trace = []
        class FakeApi:
            def find(self):
                return [reader.Device('fixture', 1)], []
            def open(self, path, reading):
                trace.append('open'); return 11
            def identity(self, handle):
                return 1
            def CreateEvent(self, *args):
                return 22
            def close(self, handle):
                trace.append(('close', handle))
        class FakeSink:
            logger = type('Logger', (), {'failed': threading_event()})
            def accept(self, raw, stamp):
                trace.append(('accept', stamp))
        clock_values = iter((100, 200, 300))
        def clock():
            value = next(clock_values); trace.append(('clock', value)); return value
        worker = capture.CaptureWorker(FakeSink(), api_factory=FakeApi, clock_ns=clock)
        def read_one(handle, event):
            trace.append('read_return'); worker.stop_event.set(); return report()
        worker.read_one = read_one
        worker.run()  # Exclusivement API factice ; aucun thread/USB réel ici.
        self.assertIsNone(worker.error)
        position = trace.index('read_return')
        self.assertEqual(trace[position + 1:position + 3], [('clock', 200), ('accept', 200)])
        self.assertIn(('close', 11), trace)
        self.assertIn(('close', 22), trace)
        self.assertIsNone(worker.handle)
        self.assertFalse(worker.daemon)


def threading_event():
    import threading
    return threading.Event()


if __name__ == '__main__':
    unittest.main()
