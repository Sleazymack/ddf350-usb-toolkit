"""Capture HID en lecture seule, sans file graphique et sans accès USB à l'import.

Seule la sous-commande explicite ``live`` ouvre une radio. ``fixture`` traite un
JSONL local. Les dates perf_counter_ns sont prises au retour de ReadFile, avant décodage : elles
mesurent les réceptions côté PC, pas la latence de la radio, du RF ou d'un servo.
Bibliothèque standard uniquement ; le lecteur existant reste inchangé.
"""
from __future__ import annotations

import argparse
from array import array
import bisect
import json
import math
from pathlib import Path
import queue
import threading
import time

from ddf350_hid import (
    ERROR_OPERATION_ABORTED, Reader, WindowsHid, decode_report,
)

SCHEMA = "ddf350-cadence-v1"
QUANTUM_NS = 10_000  # 10 us ; bornes des percentiles annoncées, pas précision fictive.
HISTOGRAM_LIMIT_NS = 1_000_000_000
COARSE_EDGES_NS = tuple(int(x * 1_000_000) for x in
    (0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 5, 10, 15, 19, 20, 21, 25, 50, 100, 1000))
LIMITATION = (
    "Horodatage monotone perf_counter_ns à la réception côté PC, avant décodage. Inclut les "
    "effets de mise en file et d'ordonnancement Windows/Python ; ne mesure pas "
    "la latence de bout en bout. Aucun compteur émetteur : les pertes avant "
    "ReadFile ne sont pas mesurables. CH1/CH2 sont des commandes après réglages "
    "radio, pas des positions de servos ni une télémétrie du véhicule."
)


class Metrics:
    """Agrégats de taille fixe ; aucun historique de rapports conservé ici."""
    def __init__(self):
        self.reports = self.valid = self.invalid = 0
        self.first_ns = self.last_ns = None
        self.intervals = self.interval_sum_ns = 0
        self.interval_min_ns = self.interval_max_ns = None
        self.histogram = array('Q', [0]) * (HISTOGRAM_LIMIT_NS // QUANTUM_NS + 1)
        self.coarse = [0] * (len(COARSE_EDGES_NS) + 1)
        self.previous_valid = None
        self.previous_valid_seq = None
        self.comparisons = self.changed_either = 0
        self.channels = {
            name: dict(first=None, last=None, minimum=None, maximum=None,
                       changed=0, total_abs_step=0, max_abs_step=0)
            for name in ('ch1', 'ch2')
        }

    def add(self, raw: bytes, timestamp_ns: int) -> dict:
        if type(timestamp_ns) is not int or timestamp_ns < 0:
            raise ValueError('monotonic_ns doit être un entier positif ou nul.')
        if self.last_ns is not None and timestamp_ns < self.last_ns:
            raise ValueError('Les horodatages doivent être croissants ou égaux.')
        if not isinstance(raw, bytes) or len(raw) > 18:
            raise ValueError('La capture brute doit contenir au plus 18 octets.')
        delta = None if self.last_ns is None else timestamp_ns - self.last_ns
        if self.first_ns is None:
            self.first_ns = timestamp_ns
        self.last_ns = timestamp_ns
        self.reports += 1
        if delta is not None:
            self.intervals += 1
            self.interval_sum_ns += delta
            self.interval_min_ns = delta if self.interval_min_ns is None else min(self.interval_min_ns, delta)
            self.interval_max_ns = delta if self.interval_max_ns is None else max(self.interval_max_ns, delta)
            self.histogram[min(delta // QUANTUM_NS, len(self.histogram) - 1)] += 1
            self.coarse[bisect.bisect_right(COARSE_EDGES_NS, delta)] += 1
        record = dict(type='report', seq=self.reports, monotonic_ns=timestamp_ns,
                      elapsed_ns=timestamp_ns - self.first_ns, interval_ns=delta,
                      raw_hex=raw.hex(), raw_length=len(raw))
        try:
            values = decode_report(raw)
        except (ValueError, TypeError) as error:
            self.invalid += 1
            record.update(valid=False, error=str(error))
            return record
        self.valid += 1
        current = (values.ch1, values.ch2)
        differences = None if self.previous_valid is None else tuple(
            value - previous for value, previous in zip(current, self.previous_valid))
        record.update(valid=True, ch1=values.ch1, ch2=values.ch2,
                      previous_valid_seq=self.previous_valid_seq,
                      delta_ch1=None if differences is None else differences[0],
                      delta_ch2=None if differences is None else differences[1])
        if differences is not None:
            self.comparisons += 1
            self.changed_either += int(any(differences))
        for index, name in enumerate(('ch1', 'ch2')):
            stats, value = self.channels[name], current[index]
            if stats['first'] is None:
                stats.update(first=value, minimum=value, maximum=value)
            stats.update(last=value, minimum=min(stats['minimum'], value),
                         maximum=max(stats['maximum'], value))
            if differences is not None:
                step = abs(differences[index])
                stats['changed'] += int(step != 0)
                stats['total_abs_step'] += step
                stats['max_abs_step'] = max(stats['max_abs_step'], step)
        self.previous_valid, self.previous_valid_seq = current, self.reports
        return record

    def percentile(self, percent: int):
        if not self.intervals:
            return None
        rank, count = math.ceil(self.intervals * percent / 100), 0
        for index, value in enumerate(self.histogram):
            count += value
            if count >= rank:
                lower = index * QUANTUM_NS
                upper = (index + 1) * QUANTUM_NS
                overflow = index == len(self.histogram) - 1
                if overflow:
                    upper = self.interval_max_ns
                # The observed maximum tightens the final occupied bucket.
                upper = min(upper, self.interval_max_ns)
                return dict(lower_ms=lower / 1e6, upper_ms=upper / 1e6,
                            estimate_ms=(lower + upper) / 2e6, overflow=overflow)
        raise AssertionError('Histogramme incohérent.')

    def summary(self) -> dict:
        span = None if self.first_ns is None else self.last_ns - self.first_ns
        bounds = (0,) + COARSE_EDGES_NS + (None,)
        return dict(
            reports_received=self.reports, valid_reports=self.valid,
            invalid_reports=self.invalid, first_monotonic_ns=self.first_ns,
            last_monotonic_ns=self.last_ns, reception_span_seconds=None if span is None else span / 1e9,
            frequency_hz=self.intervals * 1e9 / span if span else None,
            intervals=dict(count=self.intervals,
                minimum_ms=None if self.interval_min_ns is None else self.interval_min_ns / 1e6,
                mean_ms=self.interval_sum_ns / self.intervals / 1e6 if self.intervals else None,
                maximum_ms=None if self.interval_max_ns is None else self.interval_max_ns / 1e6,
                p50=self.percentile(50), p95=self.percentile(95), p99=self.percentile(99),
                percentile_method='nearest-rank, histogramme fixe ; valeur réelle dans les bornes',
                percentile_bin_ms=QUANTUM_NS / 1e6,
                histogram=[dict(lower_inclusive_ms=bounds[i] / 1e6,
                                upper_exclusive_ms=None if bounds[i + 1] is None else bounds[i + 1] / 1e6,
                                count=count) for i, count in enumerate(self.coarse)]),
            channel_changes=dict(comparisons_between_valid_reports=self.comparisons,
                changed_either=self.changed_either, unchanged_both=self.comparisons - self.changed_either,
                channels={name: dict(stats) for name, stats in self.channels.items()}),
            loss_before_readfile='unknown_no_transmitter_sequence', limitation=LIMITATION,
        )


class JsonlLogger:
    """Un seul producteur ; file bornée, écriture sur un thread séparé.

    Une file pleine rejette le NOUVEAU rapport, sans ralentir volontairement
    l'acquisition. Les agrégats sont déjà calculés ; les pertes sont explicites.
    Le flux injecté est réservé aux tests hors ligne.
    """
    def __init__(self, path, metadata, capacity=4096, *, stream=None, autostart=True):
        if not 1 <= capacity <= 65536:
            raise ValueError('La file doit contenir de 1 à 65536 rapports.')
        self.queue = queue.Queue(maxsize=capacity)
        self.stop = threading.Event()
        self.failed = threading.Event()
        self.error = None
        self.submitted = self.enqueued = self.written = self.dropped_full = self.rejected_error = 0
        self.high_water = 0
        self.stream = stream if stream is not None else Path(path).open('x', encoding='utf-8', newline='\n')
        self.owns_stream = stream is None
        try:
            self.stream.write(json.dumps(dict(type='metadata', schema=SCHEMA, **metadata), ensure_ascii=False) + '\n')
            self.stream.flush()  # Avant toute acquisition, détecte une destination inutilisable.
        except Exception:
            if self.owns_stream:
                self.stream.close()
            raise
        self.thread = threading.Thread(target=self._write_loop, name='Journal cadence DDF-350', daemon=False)
        self.started = False
        if autostart:
            self.start()

    def start(self):
        if not self.started:
            self.started = True
            self.thread.start()

    def submit(self, record):
        self.submitted += 1
        if self.failed.is_set():
            self.rejected_error += 1
            return False
        record['local_queue_drops_before'] = self.dropped_full
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            self.dropped_full += 1
            return False
        self.enqueued += 1
        self.high_water = max(self.high_water, self.queue.qsize())
        return True

    def _fail(self, error):
        self.error = f'{type(error).__name__}: {error}'
        self.failed.set()

    def _write_loop(self):
        try:
            while not self.stop.is_set() or not self.queue.empty():
                try:
                    record = self.queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                self.stream.write(json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n')
                self.written += 1
        except Exception as error:
            self._fail(error)

    def counters(self):
        return dict(submitted=self.submitted, enqueued=self.enqueued, written=self.written,
                    dropped_queue_full=self.dropped_full, rejected_after_io_error=self.rejected_error,
                    accepted_but_unwritten=self.enqueued - self.written,
                    queue_capacity=self.queue.maxsize, queue_high_water_observed=self.high_water,
                    error=self.error, complete=self.written == self.submitted and self.error is None)

    def finish(self, summary):
        self.stop.set()
        self.start()
        self.thread.join()  # Finir le journal après arrêt du producteur.
        result = dict(type='summary', schema=SCHEMA, **summary, logging=self.counters())
        try:
            if not self.failed.is_set():
                self.stream.write(json.dumps(result, ensure_ascii=False) + '\n')
                self.stream.flush()
        except Exception as error:
            self._fail(error)
        finally:
            if self.owns_stream:
                try:
                    self.stream.close()
                except Exception as error:
                    self._fail(error)
        result['logging'] = self.counters()
        return result


class Capture:
    def __init__(self, logger):
        self.metrics = Metrics()
        self.logger = logger

    def accept(self, raw, timestamp_ns):
        # Les métriques voient chaque réception même si le disque prend du retard.
        self.logger.submit(self.metrics.add(raw, timestamp_ns))


def clock_metadata(mode):
    info = time.get_clock_info('perf_counter')
    return dict(clock='time.perf_counter_ns' if mode == 'live' else 'fixture timestamps',
                timestamp_field='monotonic_ns',
                host_clock_info=dict(name='perf_counter', implementation=info.implementation,
                                     resolution_seconds=info.resolution, monotonic=info.monotonic,
                                     adjustable=info.adjustable))


class CaptureWorker(Reader):
    """Réutilise read_one et sa vidange CancelIoEx, jamais Reader.post/run."""
    def __init__(self, capture, *, api_factory=WindowsHid, clock_ns=None):
        super().__init__(events=None)
        self.name = 'Capture cadence DDF-350'
        self.daemon = False  # Ne pas abandonner un OVERLAPPED/buffer encore détenu par Windows.
        self.capture, self.api_factory = capture, api_factory
        self.clock_ns = time.perf_counter_ns if clock_ns is None else clock_ns
        self.connected_ns = self.finished_ns = None
        self.version = self.error = None

    def run(self):
        handle = event = None
        try:
            self.api = self.api_factory()
            devices, issues = self.api.find()
            if len(devices) != 1:
                raise ValueError('Une seule DDF-350 HID 0483:5750 est nécessaire. ' + '; '.join(issues[:3]))
            handle = self.api.open(devices[0].path, reading=True)
            self.version = self.api.identity(handle)
            event = self.api.CreateEvent(None, True, False, None)
            if not event:
                raise self.api.error()
            with self.handle_lock:
                self.handle = handle
            self.connected_ns = self.clock_ns()
            while not self.stop_event.is_set() and not self.capture.logger.failed.is_set():
                raw = self.read_one(handle, event)
                received_ns = self.clock_ns()  # Première opération après le retour de read_one.
                self.capture.accept(raw, received_ns)
        except Exception as error:
            aborted = isinstance(error, OSError) and error.errno == ERROR_OPERATION_ABORTED
            if not (self.stop_event.is_set() and aborted):
                self.error = f'{type(error).__name__}: {error}'
        finally:
            with self.handle_lock:
                self.handle = None
                if self.api is not None:
                    self.api.close(handle)
            if self.api is not None:
                self.api.close(event)
            self.finished_ns = self.clock_ns()


def read_fixture(path):
    """Lit aussi nos propres captures, sans conserver le fichier en mémoire."""
    with Path(path).open('r', encoding='utf-8') as source:
        line_number = 0
        while True:
            line = source.readline(65537)
            if not line:
                break
            line_number += 1
            if len(line) > 65536:
                raise ValueError(f'Fixture ligne {line_number} trop longue.')
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f'Fixture ligne {line_number} : objet attendu.')
            if row.get('type') in ('metadata', 'summary'):
                continue
            if row.get('type', 'report') != 'report':
                raise ValueError(f'Fixture ligne {line_number} : type inconnu.')
            raw_hex = row.get('raw_hex')
            if not isinstance(raw_hex, str) or len(raw_hex) > 36:
                raise ValueError(f'Fixture ligne {line_number} : raw_hex de 18 octets maximum attendu.')
            yield bytes.fromhex(raw_hex), row.get('monotonic_ns')


def run_live(capture, seconds):
    worker = CaptureWorker(capture)
    interrupted = False
    worker.start()
    # Ctrl-C est traité ici, jamais dans la pile du ReadFile en cours.
    while worker.is_alive():
        try:
            if worker.connected_ns is not None and worker.clock_ns() - worker.connected_ns >= seconds * 1e9:
                worker.request_stop()
            if capture.logger.failed.is_set():
                worker.request_stop()
            worker.join(0.02)
        except KeyboardInterrupt:
            interrupted = True
            worker.request_stop()
            # Même un second Ctrl-C attend la fin de l'annulation native.
    return dict(mode='live', requested_seconds=seconds, interrupted=interrupted,
                connected_monotonic_ns=worker.connected_ns, finished_monotonic_ns=worker.finished_ns,
                device_version=worker.version, acquisition_error=worker.error, reader_stopped=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='mode', required=True)
    for mode in ('live', 'fixture'):
        sub = subs.add_parser(mode, help='Lecture USB réelle explicite' if mode == 'live' else 'Fichier local, aucun USB')
        sub.add_argument('--output', type=Path, required=True, help='Nouveau fichier JSONL (aucun écrasement)')
        sub.add_argument('--queue-size', type=int, default=4096)
        if mode == 'live':
            sub.add_argument('--seconds', type=float, default=20)
        else:
            sub.add_argument('input', type=Path)
    args = parser.parse_args(argv)
    if not 1 <= args.queue_size <= 65536:
        parser.error('--queue-size doit être compris entre 1 et 65536.')
    if args.mode == 'live' and (not math.isfinite(args.seconds) or not 0.1 <= args.seconds <= 86400):
        parser.error('--seconds doit être compris entre 0,1 et 86400.')
    metadata = dict(mode=args.mode, **clock_metadata(args.mode),
                    expected_report_bytes=18, usb_vid='0483', usb_pid='5750', limitation=LIMITATION)
    # Échec de création du fichier = aucune tentative d'accès USB.
    logger = JsonlLogger(args.output, metadata, args.queue_size)
    capture, status = Capture(logger), dict(mode=args.mode, acquisition_error=None)
    try:
        if args.mode == 'live':
            status = run_live(capture, args.seconds)
        else:
            for raw, timestamp_ns in read_fixture(args.input):
                capture.accept(raw, timestamp_ns)
                if logger.failed.is_set():
                    break
    except KeyboardInterrupt:
        status['interrupted'] = True
    except Exception as error:
        status['acquisition_error'] = f'{type(error).__name__}: {error}'
    summary = logger.finish(dict(capture=capture.metrics.summary(), status=status))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if status.get('acquisition_error') or summary['logging']['error']:
        return 1
    return 0 if summary['logging']['complete'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
