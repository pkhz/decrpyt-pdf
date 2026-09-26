import hashlib
import itertools
import json
import multiprocessing as mp
import os
import string
import struct
import time
from typing import Optional

from pypdf import PdfReader
from Crypto.Cipher import ARC4

PASSWORD_PADDING = bytes.fromhex(
    "28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A"
)

_GUESS_STOP_REQUESTED = False
_GUESS_PAUSED = False
_STOP_EVENT = None
_PAUSE_EVENT = None
_SESSION_CHECKPOINT = None


class PauseRequested(RuntimeError):
    def __init__(self, checkpoint):
        super().__init__("Guessing paused by user.")
        self.checkpoint = checkpoint


def stop_guessing():
    global _GUESS_STOP_REQUESTED, _STOP_EVENT
    _GUESS_STOP_REQUESTED = True
    if _STOP_EVENT is not None:
        _STOP_EVENT.set()


def clear_guess_stop():
    global _GUESS_STOP_REQUESTED, _STOP_EVENT
    _GUESS_STOP_REQUESTED = False
    if _STOP_EVENT is not None:
        _STOP_EVENT.clear()


def pause_guessing():
    global _GUESS_PAUSED, _PAUSE_EVENT
    _GUESS_PAUSED = True
    if _PAUSE_EVENT is not None:
        _PAUSE_EVENT.set()


def resume_guessing():
    global _GUESS_PAUSED, _PAUSE_EVENT
    _GUESS_PAUSED = False
    if _PAUSE_EVENT is not None:
        _PAUSE_EVENT.clear()


def clear_session_checkpoint():
    global _SESSION_CHECKPOINT
    _SESSION_CHECKPOINT = None


def save_checkpoint_to_json(checkpoint, path):
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(checkpoint, fp, indent=2, ensure_ascii=False)


def load_checkpoint_from_json(path):
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)


def checkpoint_matches_pdf(checkpoint, pdf_path):
    if not checkpoint:
        return False
    checkpoint_pdf = checkpoint.get("pdf_path")
    if not checkpoint_pdf:
        return True
    if not pdf_path:
        return False
    return os.path.abspath(str(checkpoint_pdf)) == os.path.abspath(str(pdf_path))


def is_guess_paused():
    global _PAUSE_EVENT
    if _PAUSE_EVENT is not None:
        return _PAUSE_EVENT.is_set() or _GUESS_PAUSED
    return _GUESS_PAUSED


def current_checkpoint():
    return _SESSION_CHECKPOINT


def is_guess_stopped():
    global _STOP_EVENT
    if _STOP_EVENT is not None:
        return _STOP_EVENT.is_set() or _GUESS_STOP_REQUESTED
    return _GUESS_STOP_REQUESTED


def pad_password(password: bytes) -> bytes:
    if isinstance(password, str):
        password = password.encode("utf-8", errors="ignore")
    return (password + PASSWORD_PADDING)[:32]


def extract_pdf_encryption_data(pdf_path: str):
    reader = PdfReader(pdf_path)
    encrypt = reader.trailer["/Encrypt"]

    O = encrypt["/O"]
    U = encrypt["/U"]
    P = int(encrypt["/P"])
    ID = reader.trailer["/ID"]
    document_id = ID[0].original_bytes

    return O, U, P, document_id


def derive_file_key(password_padded, O, P, document_id):
    P_bytes = struct.pack("<i", P)
    data = password_padded + O + P_bytes + document_id

    key = hashlib.md5(data).digest()

    for _ in range(50):
        key = hashlib.md5(key).digest()

    return key[:16]


def calculate_U(file_key, ID0, encrypt_metadata=True):
    data = (
        b"\x28\xbf\x4e\x5e\x4e\x75\x8a\x41"
        b"\x64\x00\x4e\x56\xff\xfa\x01\x08"
        b"\x2e\x2e\x00\xb6\xd0\x68\x3e\x80"
        b"\x2f\x0c\xa9\xfe\x64\x53\x69\x7a"
        + ID0
    )

    if not encrypt_metadata:
        data += b"\xff\xff\xff\xff"

    digest = hashlib.md5(data).digest()
    result = ARC4.new(file_key).encrypt(digest)

    for i in range(1, 20):
        key = bytes(b ^ i for b in file_key)
        result = ARC4.new(key).encrypt(result)

    return result


def validate_password_by_algorithm(pdf_path: str, password) -> bool:
    reader = PdfReader(pdf_path)

    if not reader.is_encrypted:
        return True

    encrypt = reader.trailer["/Encrypt"]
    O = encrypt["/O"]
    U = encrypt["/U"]
    P = int(encrypt["/P"])
    document_id = reader.trailer["/ID"][0].original_bytes

    file_key = derive_file_key(pad_password(password), O, P, document_id)

    calculated_true = calculate_U(file_key, document_id, encrypt_metadata=True)
    calculated_false = calculate_U(file_key, document_id, encrypt_metadata=False)

    return (
        calculated_true == U or calculated_true == U[:16] or
        calculated_false == U or calculated_false == U[:16]
    )


def build_character_set(
    lowercase: bool = False,
    uppercase: bool = False,
    numbers: bool = False,
    symbols: bool = False,
    custom_chars: str = "",
) -> str:
    charset = []

    if lowercase:
        charset.extend(string.ascii_lowercase)
    if uppercase:
        charset.extend(string.ascii_uppercase)
    if numbers:
        charset.extend(string.digits)
    if symbols:
        charset.extend(string.punctuation)
    if custom_chars:
        charset.extend(custom_chars)

    return "".join(dict.fromkeys(charset))


def parse_custom_pattern(pattern: str):
    if not pattern:
        raise ValueError("Custom pattern cannot be empty.")

    tokens = []
    i = 0
    while i < len(pattern):
        if pattern[i] == "?":
            j = i + 1
            digits = ""
            while j < len(pattern) and pattern[j].isdigit():
                digits += pattern[j]
                j += 1

            charset = None
            if j < len(pattern) and pattern[j] == "[":
                end = pattern.find("]", j)
                if end == -1:
                    raise ValueError(f"Custom pattern has an unclosed charset in: {pattern}")
                charset = pattern[j + 1:end]
                j = end + 1

            tokens.append({
                "type": "unknown",
                "length": int(digits) if digits else 1,
                "charset": charset,
            })
            i = j
        else:
            start = i
            while i < len(pattern) and pattern[i] != "?":
                i += 1
            tokens.append({"type": "literal", "value": pattern[start:i]})

    return tokens


def generate_custom_pattern_candidates(pattern: str, default_charset: str):
    tokens = parse_custom_pattern(pattern)
    if not tokens:
        return

    def recurse(index, current):
        if index == len(tokens):
            yield current
            return

        token = tokens[index]
        if token["type"] == "literal":
            for result in recurse(index + 1, current + token["value"]):
                yield result
            return

        length = max(1, int(token["length"]))
        charset = token["charset"] if token["charset"] is not None else default_charset
        if not charset:
            raise ValueError("Custom pattern requires at least one enabled character set for each unknown slot.")

        for chars in itertools.product(charset, repeat=length):
            for result in recurse(index + 1, current + "".join(chars)):
                yield result

    yield from recurse(0, "")


def total_custom_pattern_candidates(pattern: str, default_charset: str) -> int:
    tokens = parse_custom_pattern(pattern)
    total = 1
    for token in tokens:
        if token["type"] == "unknown":
            charset = token["charset"] if token["charset"] is not None else default_charset
            if not charset:
                return 0
            total *= len(charset) ** max(1, token["length"])
    return total


def generate_pattern_candidates(prefix: str, unknown_count: int, suffix: str, charset: str):
    if unknown_count <= 0:
        yield f"{prefix}{suffix}"
        return

    for chars in itertools.product(charset, repeat=unknown_count):
        yield f"{prefix}{''.join(chars)}{suffix}"


def total_pattern_candidates(prefix: str, unknown_count: int, suffix: str, charset: str) -> int:
    if unknown_count <= 0:
        return 1
    return len(charset) ** unknown_count


def candidate_from_index(charset: str, unknown_count: int, index: int) -> str:
    if unknown_count <= 0:
        return ""

    base = len(charset)
    digits = []
    current = index

    for _ in range(unknown_count):
        digits.append(current % base)
        current //= base

    digits.reverse()
    return "".join(charset[d] for d in digits)


def _parallel_worker(
    pdf_path: str,
    prefix: str,
    unknown_count: int,
    suffix: str,
    charset: str,
    start: int,
    end: int,
    worker_id: int,
    tried_counter,
    found_queue,
    progress_queue,
    stop_event,
    pause_event,
):
    local_count = 0
    for index in range(start, end):
        if stop_event.is_set() or pause_event.is_set():
            return None

        candidate = candidate_from_index(charset, unknown_count, index)
        full_password = f"{prefix}{candidate}{suffix}"

        try:
            from main import check_password

            is_valid = check_password(pdf_path, full_password)
        except ImportError:
            is_valid = validate_password_by_algorithm(pdf_path, full_password)

        local_count += 1
        tried_counter.value += 1

        if progress_queue is not None:
            progress_queue.put((worker_id, start + local_count, start, end))

        if is_valid:
            winner_attempts = local_count
            found_queue.put({
                "password": full_password,
                "worker_id": f"worker_{worker_id}",
                "index": start + local_count,
                "attempts": winner_attempts,
            })
            return {
                "password": full_password,
                "worker_id": f"worker_{worker_id}",
                "index": start + local_count,
                "attempts": winner_attempts,
            }

    return None


def guess_password_by_pattern(
    pdf_path: str,
    prefix: str = "",
    unknown_count: int = 4,
    suffix: str = "",
    lowercase: bool = False,
    uppercase: bool = False,
    numbers: bool = False,
    symbols: bool = False,
    custom_chars: str = "",
    max_attempts=None,
    progress_callback=None,
    process_count: int = 1,
    custom_pattern: str = "",
    resume_session: Optional[dict] = None,
):
    global _SESSION_CHECKPOINT

    charset = build_character_set(
        lowercase=lowercase,
        uppercase=uppercase,
        numbers=numbers,
        symbols=symbols,
        custom_chars=custom_chars,
    )

    if custom_pattern:
        if not charset:
            raise ValueError("At least one character set must be enabled for custom pattern mode.")
        total = total_custom_pattern_candidates(custom_pattern, charset)
        count = 0
        skip_remaining = False
        last_candidate = None
        if resume_session is not None:
            count = int(resume_session.get("tried", 0))
            last_candidate = resume_session.get("last_candidate")
            skip_remaining = last_candidate is not None

        for candidate in generate_custom_pattern_candidates(custom_pattern, charset):
            if skip_remaining:
                if candidate == last_candidate:
                    skip_remaining = False
                continue

            if is_guess_stopped():
                raise KeyboardInterrupt("Guessing stopped by user.")
            if is_guess_paused():
                _SESSION_CHECKPOINT = {
                    "mode": "custom_pattern",
                    "prefix": prefix,
                    "suffix": suffix,
                    "unknown_count": unknown_count,
                    "charset": charset,
                    "custom_pattern": custom_pattern,
                    "tried": count,
                    "total": total,
                    "last_candidate": candidate,
                    "status": "paused",
                }
                raise PauseRequested(_SESSION_CHECKPOINT)

            count += 1
            if max_attempts is not None and count > max_attempts:
                break

            if progress_callback is not None:
                try:
                    progress_callback(count, total, {"worker_0": (count, total)})
                except TypeError:
                    progress_callback(count, total)

            try:
                from main import check_password

                if check_password(pdf_path, candidate):
                    return candidate
            except ImportError:
                if validate_password_by_algorithm(pdf_path, candidate):
                    return candidate

        if progress_callback is not None:
            try:
                progress_callback(count, total, {"worker_0": (count, total)})
            except TypeError:
                progress_callback(count, total)

        return None

    if not charset:
        raise ValueError("At least one character set must be enabled.")

    total = total_pattern_candidates(prefix, unknown_count, suffix, charset)
    if process_count <= 1:
        count = int(resume_session.get("tried", 0)) if resume_session else 0
        resume_start = int(resume_session.get("next_index", 0)) if resume_session else 0
        candidate_index = -1
        worker_progress = {"worker_0": (count, total)}
        for candidate in generate_pattern_candidates(prefix, unknown_count, suffix, charset):
            candidate_index += 1
            if candidate_index < resume_start:
                continue

            if is_guess_stopped():
                raise KeyboardInterrupt("Guessing stopped by user.")
            if is_guess_paused():
                _SESSION_CHECKPOINT = {
                    "mode": "standard",
                    "prefix": prefix,
                    "suffix": suffix,
                    "unknown_count": unknown_count,
                    "charset": charset,
                    "custom_pattern": "",
                    "tried": count,
                    "next_index": candidate_index + 1,
                    "total": total,
                    "last_candidate": candidate,                    "last_processed_index": candidate_index,
                    "last_worker_id": "worker_0",                    "status": "paused",
                }
                raise PauseRequested(_SESSION_CHECKPOINT)

            count += 1
            worker_progress["worker_0"] = (count, total)
            if max_attempts is not None and count > max_attempts:
                break

            if progress_callback is not None:
                try:
                    progress_callback(count, total, worker_progress)
                except TypeError:
                    progress_callback(count, total)

            try:
                from main import check_password

                if check_password(pdf_path, candidate):
                    return candidate
            except ImportError:
                if validate_password_by_algorithm(pdf_path, candidate):
                    return candidate

        if progress_callback is not None:
            try:
                progress_callback(count, total, worker_progress)
            except TypeError:
                progress_callback(count, total)

        return None

    global _STOP_EVENT, _PAUSE_EVENT
    ctx = mp.get_context("spawn")
    _STOP_EVENT = ctx.Event()
    _PAUSE_EVENT = ctx.Event()
    _STOP_EVENT.clear()
    _PAUSE_EVENT.clear()
    clear_guess_stop()
    resume_guessing()

    resume_start = int(resume_session.get("next_index", 0)) if resume_session else 0
    resume_start = max(0, min(resume_start, total))
    if resume_start >= total:
        return None

    tried_counter = ctx.Value("i", 0)
    found_queue = ctx.Queue()
    progress_queue = ctx.Queue()
    worker_count = max(1, min(int(process_count), mp.cpu_count() or 1))
    workers = []
    worker_progress = {}
    resume_cursor = resume_start

    for worker_index in range(worker_count):
        remaining = max(1, total - resume_start)
        start = resume_start + ((remaining * worker_index) // worker_count)
        end = resume_start + ((remaining * (worker_index + 1)) // worker_count)
        worker = ctx.Process(
            target=_parallel_worker,
            args=(pdf_path, prefix, unknown_count, suffix, charset, start, end, worker_index, tried_counter, found_queue, progress_queue, _STOP_EVENT, _PAUSE_EVENT),
        )
        worker.start()
        workers.append(worker)

    try:
        while any(worker.is_alive() for worker in workers):
            if is_guess_stopped():
                for worker in workers:
                    worker.terminate()
                raise KeyboardInterrupt("Guessing stopped by user.")

            if is_guess_paused():
                for worker in workers:
                    worker.terminate()
                latest_worker = "worker_0"
                latest_index = resume_start
                for key, value in worker_progress.items():
                    if not value:
                        continue
                    current_index = value[0]
                    if current_index > latest_index:
                        latest_index = current_index
                        latest_worker = key
                _SESSION_CHECKPOINT = {
                    "mode": "standard",
                    "prefix": prefix,
                    "suffix": suffix,
                    "unknown_count": unknown_count,
                    "charset": charset,
                    "custom_pattern": custom_pattern,
                    "tried": int(tried_counter.value),
                    "next_index": max(resume_start, resume_cursor),
                    "total": total,
                    "last_processed_index": latest_index,
                    "last_worker_id": latest_worker,
                    "status": "paused",
                }
                raise PauseRequested(_SESSION_CHECKPOINT)

            while not progress_queue.empty():
                worker_id, current_index, assigned_start, assigned_end = progress_queue.get_nowait()
                worker_progress[f"worker_{worker_id}"] = (current_index, total, assigned_start, assigned_end)
                resume_cursor = max(resume_cursor, current_index)

            if progress_callback is not None:
                try:
                    progress_callback(int(tried_counter.value), total, worker_progress.copy())
                except TypeError:
                    progress_callback(int(tried_counter.value), total)

            if not found_queue.empty():
                found = found_queue.get_nowait()
                for worker in workers:
                    worker.terminate()
                return found if isinstance(found, dict) else found

            time.sleep(0.15)

        while not progress_queue.empty():
            worker_id, current_index, assigned_start, assigned_end = progress_queue.get_nowait()
            worker_progress[f"worker_{worker_id}"] = (current_index, total, assigned_start, assigned_end)

        if progress_callback is not None:
            try:
                progress_callback(int(tried_counter.value), total, worker_progress.copy())
            except TypeError:
                progress_callback(int(tried_counter.value), total)
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=2)

        _STOP_EVENT = None
        _PAUSE_EVENT = None

    if not found_queue.empty():
        found = found_queue.get_nowait()
        return found if isinstance(found, dict) else found

    return None
