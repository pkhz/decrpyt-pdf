import os
import sys
import time

from PySide6.QtCore import QDateTime, QObject, QThread, Signal, QTime
from pypdf import PdfReader
from PySide6.QtGui import QFont, QFontDatabase, QTextOption
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QFileDialog,
    QMessageBox,
    QCheckBox,
    QSpinBox,
    QFormLayout,
    QHBoxLayout,
    QToolButton,
    QTabWidget,
    QGroupBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QTextEdit,
    QSizePolicy,
)

from main import check_password
from combined_pdf import (
    PauseRequested,
    build_character_set,
    checkpoint_matches_pdf,
    clear_guess_stop,
    clear_session_checkpoint,
    current_checkpoint,
    guess_password_by_pattern,
    load_checkpoint_from_json,
    pause_guessing,
    resume_guessing,
    save_checkpoint_to_json,
    stop_guessing,
)


class CharsetDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Global character set")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        self.lowercase = QCheckBox("Lowercase: a-z")
        self.uppercase = QCheckBox("Uppercase: A-Z")
        self.numbers = QCheckBox("Numbers: 0-9")
        self.symbols = QCheckBox("Symbols: !@#$...")
        self.custom = QLineEdit("")
        self.custom.setPlaceholderText("Custom characters")

        layout.addWidget(self.lowercase)
        layout.addWidget(self.uppercase)
        layout.addWidget(self.numbers)
        layout.addWidget(self.symbols)
        layout.addWidget(QLabel("Custom:"))
        layout.addWidget(self.custom)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return {
            "lowercase": self.lowercase.isChecked(),
            "uppercase": self.uppercase.isChecked(),
            "numbers": self.numbers.isChecked(),
            "symbols": self.symbols.isChecked(),
            "custom": self.custom.text(),
        }


class CustomPatternInput(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._global_charset_enabled = True

    def set_global_charset_enabled(self, enabled):
        self._global_charset_enabled = enabled

    def insert_unknown_slot(self, count=1, charset=""):
        text = self.text()
        cursor = self.cursorPosition()
        replacement = f"?{count}"
        if not self._global_charset_enabled and charset:
            replacement = f"?{count}[{charset}]"
        self.setText(text[:cursor] + replacement + text[cursor:])
        self.setCursorPosition(cursor + len(replacement))

    def selected_unknown_slot(self):
        text = self.text()
        cursor = self.cursorPosition()
        for match in __import__("re").finditer(r"\?[0-9]*(?:\[[^\]]*\])?", text):
            start, end = match.span()
            if start <= cursor <= end:
                return match.group(0), start, end
        return None, None, None

    def open_slot_editor(self):
        token, start, end = self.selected_unknown_slot()
        if token is None:
            self.insert_unknown_slot()
            token, start, end = self.selected_unknown_slot()
        if token is None:
            return

        text = self.text()
        count = 1
        custom_chars = ""
        if token.startswith("?"):
            rest = token[1:]
            if "[" in rest:
                head, bracket = rest.split("[", 1)
                if head.isdigit():
                    count = int(head)
                custom_chars = bracket.rstrip("]")
            elif rest.isdigit():
                count = int(rest)

        dialog = QDialog(self)
        dialog.setWindowTitle("Unknown slot settings")
        dialog_layout = QGridLayout(dialog)

        count_spin = QSpinBox(dialog)
        count_spin.setRange(1, 12)
        count_spin.setValue(count)

        charset_input = QLineEdit(custom_chars, dialog)
        charset_input.setPlaceholderText("Example: abc123")
        charset_input.setEnabled(not self._global_charset_enabled)

        summary_label = QLabel("Using global charset")
        summary_label.setWordWrap(True)
        summary_label.setEnabled(self._global_charset_enabled)

        lower = QCheckBox("a-z", dialog)
        upper = QCheckBox("A-Z", dialog)
        digits = QCheckBox("0-9", dialog)
        symbols = QCheckBox("!@#", dialog)
        lower.setEnabled(not self._global_charset_enabled)
        upper.setEnabled(not self._global_charset_enabled)
        digits.setEnabled(not self._global_charset_enabled)
        symbols.setEnabled(not self._global_charset_enabled)

        lower.setChecked(any(ch in custom_chars for ch in "abcdefghijklmnopqrstuvwxyz"))
        upper.setChecked(any(ch in custom_chars for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        digits.setChecked(any(ch in custom_chars for ch in "0123456789"))
        symbols.setChecked(any(ch in custom_chars for ch in "!@#$%^&*()_+-=[]{};:,.<>/?\\|`~"))

        dialog_layout.addWidget(QLabel("Length:"), 0, 0)
        dialog_layout.addWidget(count_spin, 0, 1)
        if self._global_charset_enabled:
            dialog_layout.addWidget(QLabel("Charset for this slot:"), 1, 0)
            dialog_layout.addWidget(summary_label, 1, 1)
        else:
            dialog_layout.addWidget(QLabel("Charset for this slot:"), 1, 0)
            dialog_layout.addWidget(charset_input, 1, 1)
        dialog_layout.addWidget(QLabel("Quick sets:"), 2, 0)
        dialog_layout.addWidget(lower, 2, 1)
        dialog_layout.addWidget(upper, 3, 1)
        dialog_layout.addWidget(digits, 4, 1)
        dialog_layout.addWidget(symbols, 5, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        dialog_layout.addWidget(buttons, 6, 0, 1, 2)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        if dialog.exec() != QDialog.Accepted:
            return

        replacement = f"?{max(1, count_spin.value())}"
        if not self._global_charset_enabled:
            local_chars = charset_input.text().strip()
            if lower.isChecked():
                local_chars += "abcdefghijklmnopqrstuvwxyz"
            if upper.isChecked():
                local_chars += "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            if digits.isChecked():
                local_chars += "0123456789"
            if symbols.isChecked():
                local_chars += "!@#$%^&*()_+-=[]{};:,.<>/?\\|`~"
            local_chars = "".join(dict.fromkeys(local_chars))
            if local_chars:
                replacement = f"?{max(1, count_spin.value())}[{local_chars}]"

        new_text = text[:start] + replacement + text[end:]
        self.setText(new_text)
        self.setCursorPosition(start + len(replacement))


class GuessWorker(QObject):
    progress = Signal(int, int, object)
    finished = Signal(object)
    paused = Signal(object)
    error = Signal(str)

    def __init__(self, pdf_path, **kwargs):
        super().__init__()
        self.pdf_path = pdf_path
        self.kwargs = kwargs

    def run(self):
        try:
            result = guess_password_by_pattern(self.pdf_path, progress_callback=self._progress, **self.kwargs)
            self.finished.emit(result)
        except PauseRequested as exc:
            self.paused.emit(exc.checkpoint)
        except KeyboardInterrupt:
            self.finished.emit(None)
        except Exception as exc:
            self.error.emit(str(exc))

    def _progress(self, tried, total, worker_progress=None):
        self.progress.emit(tried, total, worker_progress or {})


class MainWindow(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("PDF Password Tool")
        self.resize(600, 500)

        self.pdf_path = None
        self._guess_thread = None
        self._guess_in_progress = False
        self._is_paused = False
        self._search_started_at = None
        self._last_worker_progress = {}

        layout = QVBoxLayout()

        self.file_label = QLabel("No PDF selected")
        self.encryption_label = QLabel("Encryption: not checked")
        self.runtime_estimate_label = QLabel("Estimated runtime before guess: --")
        self.progress_label = QLabel("Progress: 0 / 0\nElapsed: 00:00:00\nSpeed: 0 /s (0 /min)\nETA: --\nFinish: --")
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QTextEdit.WidgetWidth)
        self.log_output.setWordWrapMode(QTextOption.WrapAnywhere)
        self.log_output.setMinimumWidth(300)
        self.log_output.setMinimumHeight(220)
        self.log_output.setPlaceholderText("Search log will appear here...")
        self._last_tried_count = 0
        self._last_candidate = ""
        self._checkpoint = None

        select_button = QPushButton("Select PDF")
        select_button.clicked.connect(self.select_pdf)

        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.Password)

        self.show_password_button = QToolButton()
        self.show_password_button.setText("\ue8f4")
        self.show_password_button.setToolTip("Show password")
        self.show_password_button.setFixedSize(36, 36)
        self.show_password_button.clicked.connect(self.toggle_password_visibility)

        font_id = QFontDatabase.addApplicationFont(
            "fonts/Material_Symbols_Outlined-20-100-0_-25.ttf"
        )

        families = QFontDatabase.applicationFontFamilies(font_id)
        print(families)

        material_font = QFont(families[0])
        material_font.setPointSize(18)
        self.show_password_button.setFont(material_font)

        password_row = QHBoxLayout()
        password_row.addWidget(self.password)
        password_row.addWidget(self.show_password_button)

        verify_button = QPushButton("Verify Password")
        verify_button.clicked.connect(self.verify_password)

        self.guess_button = QPushButton("Guess by Pattern")
        self.guess_button.setEnabled(False)
        self.guess_button.clicked.connect(self.guess_pattern_password)

        self.pause_button = QPushButton("Pause")
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self.pause_guess)

        self.stop_guess_button = QPushButton("Stop Guess")
        self.stop_guess_button.setEnabled(False)
        self.stop_guess_button.clicked.connect(self.stop_guess)

        self.load_checkpoint_button = QPushButton("Load checkpoint")
        self.load_checkpoint_button.clicked.connect(self.load_saved_checkpoint)

        self.pause_action_row = QHBoxLayout()
        self.continue_pause_button = QPushButton("Continue")
        self.continue_pause_button.setVisible(False)
        self.continue_pause_button.clicked.connect(self.continue_from_pause)
        self.save_pause_button = QPushButton("Save JSON")
        self.save_pause_button.setVisible(False)
        self.save_pause_button.clicked.connect(self.save_pause_checkpoint)
        self.pause_action_row.addWidget(self.continue_pause_button)
        self.pause_action_row.addWidget(self.save_pause_button)

        self.pause_controls_widget = QWidget()
        self.pause_controls_widget.setLayout(self.pause_action_row)
        self.pause_controls_widget.setVisible(False)

        self.prefix_input = QLineEdit("A")
        self.prefix_input.setPlaceholderText("Known prefix")
        self.unknown_count = QSpinBox()
        self.unknown_count.setRange(1, 12)
        self.unknown_count.setValue(4)
        self.suffix_input = QLineEdit("2024")
        self.suffix_input.setPlaceholderText("Suffix")
        self.process_count = QSpinBox()
        self.process_count.setEnabled(False)
        self.process_count.setRange(1, max(1, os.cpu_count() or 1))
        self.process_count.setValue(min(4, max(1, os.cpu_count() or 1)))

        self.lowercase = QCheckBox("Lowercase: a-z")
        self.lowercase.setEnabled(False)
        self.uppercase = QCheckBox("Uppercase: A-Z")
        self.uppercase.setEnabled(False)
        self.numbers = QCheckBox("Numbers: 0-9")
        self.numbers.setEnabled(False)
        self.symbols = QCheckBox("Symbols: !@#$...")
        self.symbols.setEnabled(False)
        self.custom = QLineEdit("")
        self.custom.setEnabled(False)
        self.custom.setPlaceholderText("Custom chars")

        self.custom_pattern_input = CustomPatternInput()
        self.custom_pattern_input.setText("abc?1?23?xyz2")
        self.custom_pattern_input.setPlaceholderText("Example: abc?1?23?xyz2")
        self.custom_pattern_input.setEnabled(False)

        self.add_unknown_slot_button = QPushButton("Insert unknown slot")
        self.add_unknown_slot_button.setEnabled(False)
        self.add_unknown_slot_button.clicked.connect(lambda: self.custom_pattern_input.insert_unknown_slot())

        self.edit_selected_slot_button = QPushButton("Edit selected slot")
        self.edit_selected_slot_button.setEnabled(False)
        self.edit_selected_slot_button.clicked.connect(self.custom_pattern_input.open_slot_editor)

        self.use_global_charset_checkbox = QCheckBox("Use global character set for unknown slots")
        self.use_global_charset_checkbox.setChecked(True)
        self.use_global_charset_checkbox.setEnabled(False)
        self.use_global_charset_checkbox.stateChanged.connect(self.apply_custom_pattern_charset_mode)
        self.global_charset_dialog = CharsetDialog(self)

        self.cpu_usage_label = QLabel()
        self.worker_progress_label = QLabel("Worker progress: none")
        self.worker_recommendation_label = QLabel("Recommended workers: auto")
        self.worker_recommendation_label.setWordWrap(True)
        self.worker_recommendation_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.thread_status_label = QLabel("Thread status: ready")
        self.recommend_workers_button = QPushButton("Recommend workers")
        self.recommend_workers_button.setEnabled(False)
        self.recommend_workers_button.clicked.connect(self.recommend_workers_for_search)
        self.refresh_cpu_summary()
        self.process_count.valueChanged.connect(self.refresh_cpu_summary)
        for field in (self.lowercase, self.uppercase, self.numbers, self.symbols):
            field.toggled.connect(self.refresh_cpu_summary)
        self.custom.textChanged.connect(self.refresh_cpu_summary)

        standard_tab = QWidget()
        standard_form = QFormLayout()
        standard_form.addRow("Known prefix:", self.prefix_input)
        standard_form.addRow("Unknown digits:", self.unknown_count)
        standard_form.addRow("Suffix:", self.suffix_input)
        standard_form.addRow("Workers:", self.process_count)
        standard_tab.setLayout(standard_form)

        self.custom_group = QGroupBox("Custom Pattern")
        self.custom_group.setEnabled(False)
        custom_layout = QVBoxLayout()
        custom_layout.addWidget(QLabel("Pattern builder: type literals directly or insert unknown slots below. Click a slot in the text, then edit it with the controls."))
        custom_layout.addWidget(self.custom_pattern_input)

        slot_buttons = QHBoxLayout()
        slot_buttons.addWidget(self.add_unknown_slot_button)
        slot_buttons.addWidget(self.edit_selected_slot_button)
        custom_layout.addLayout(slot_buttons)
        custom_layout.addWidget(self.use_global_charset_checkbox)
        custom_layout.addWidget(QLabel("Global default charset for unspecified unknown slots:"))
        self.custom_group.setLayout(custom_layout)

        self.custom_tab = QWidget()
        self.custom_tab.setEnabled(False)
        custom_tab_layout = QVBoxLayout()
        custom_tab_layout.addWidget(self.custom_group)
        self.custom_tab.setLayout(custom_tab_layout)

        self.set_guess_controls_enabled(False)

        tabs = QTabWidget()
        tabs.addTab(standard_tab, "Prefix / Suffix")
        # Custom pattern is intentionally disabled for now while it is still WIP.

        layout.addWidget(self.file_label)
        layout.addWidget(self.encryption_label)
        layout.addWidget(self.runtime_estimate_label)
        layout.addWidget(select_button)
        layout.addLayout(password_row)
        layout.addWidget(verify_button)
        layout.addWidget(self.progress_label)
        layout.addWidget(tabs)
        layout.addWidget(self.cpu_usage_label)
        layout.addWidget(self.recommend_workers_button)
        layout.addWidget(self.worker_recommendation_label)
        layout.addWidget(self.thread_status_label)
        layout.addWidget(self.worker_progress_label)

        charset_group = QGroupBox("Character sets")
        charset_layout = QVBoxLayout()

        charset_row_1 = QHBoxLayout()
        charset_row_1.addWidget(self.lowercase)
        charset_row_1.addWidget(self.uppercase)
        charset_row_1.addWidget(self.numbers)
        charset_row_1.addWidget(self.symbols)
        charset_layout.addLayout(charset_row_1)

        charset_layout.addWidget(QLabel("Custom:"))
        charset_layout.addWidget(self.custom)
        charset_group.setLayout(charset_layout)
        layout.addWidget(charset_group)

        layout.addWidget(self.guess_button)
        layout.addWidget(self.pause_button)
        layout.addWidget(self.stop_guess_button)
        layout.addWidget(self.load_checkpoint_button)
        layout.addWidget(self.pause_controls_widget)

        log_group = QGroupBox("Search log")
        log_layout = QVBoxLayout()
        log_layout.addWidget(self.log_output)
        log_group.setLayout(log_layout)

        outer_layout = QHBoxLayout()
        outer_layout.addLayout(layout, 3)
        outer_layout.addWidget(log_group, 1)
        self.setLayout(outer_layout)

    def detect_encryption_type(self, pdf_path):
        try:
            reader = PdfReader(pdf_path)
            if not reader.is_encrypted:
                return {
                    "encrypted": False,
                    "matched": False,
                    "message": "Encryption: not encrypted",
                }

            encrypt = reader.trailer.get("/Encrypt")
            if encrypt is None:
                return {
                    "encrypted": True,
                    "matched": False,
                    "message": "Encryption: encrypted but metadata not available",
                }

            cf = encrypt.get("/CF") or {}
            std_cf = cf.get("/StdCF") if isinstance(cf, dict) else {}
            std_cf_dict = std_cf if isinstance(std_cf, dict) else {}

            v = encrypt.get("/V")
            r = encrypt.get("/R")
            length = encrypt.get("/Length")
            stmf = encrypt.get("/StmF")
            strf = encrypt.get("/StrF")
            cfm = std_cf_dict.get("/CFM")
            std_length = std_cf_dict.get("/Length")
            auth_event = std_cf_dict.get("/AuthEvent")

            matched = (
                v == 4 and r == 4 and length == 128 and
                stmf == "/StdCF" and strf == "/StdCF" and
                cfm == "/AESV2" and std_length == 16 and auth_event == "/DocOpen"
            )

            if matched:
                message = (
                    "Encryption: matches Standard/AESV2 pattern "
                    "(V=4, R=4, Length=128, StdCF/AESV2)"
                )
            else:
                message = (
                    "Encryption: detected but not matching expected pattern "
                    f"(V={v}, R={r}, Length={length}, StmF={stmf}, StrF={strf}, "
                    f"CFM={cfm}, StdLength={std_length}, AuthEvent={auth_event})"
                )

            return {
                "encrypted": True,
                "matched": matched,
                "message": message,
            }
        except Exception as exc:
            return {
                "encrypted": False,
                "matched": False,
                "message": f"Encryption: could not read metadata ({exc})",
            }

    def apply_custom_pattern_charset_mode(self, state):
        enabled = state == 2
        self.custom_pattern_input.set_global_charset_enabled(enabled)
        self.custom_pattern_input.setEnabled(True)

        for field in (self.lowercase, self.uppercase, self.numbers, self.symbols, self.custom):
            field.setEnabled(enabled)

        if enabled:
            self.global_charset_dialog.show()
            self.global_charset_dialog.raise_()
            self.global_charset_dialog.activateWindow()

    def set_guess_controls_enabled(self, enabled):
        self.guess_button.setEnabled(enabled)
        self.pause_button.setEnabled(enabled and self._guess_thread is not None and self._guess_thread.isRunning())
        self.stop_guess_button.setEnabled(enabled and self._guess_thread is not None and self._guess_thread.isRunning())
        self.process_count.setEnabled(enabled)
        self.recommend_workers_button.setEnabled(enabled)
        self.lowercase.setEnabled(enabled and self.use_global_charset_checkbox.isChecked())
        self.uppercase.setEnabled(enabled and self.use_global_charset_checkbox.isChecked())
        self.numbers.setEnabled(enabled and self.use_global_charset_checkbox.isChecked())
        self.symbols.setEnabled(enabled and self.use_global_charset_checkbox.isChecked())
        self.custom.setEnabled(enabled and self.use_global_charset_checkbox.isChecked())
        self.prefix_input.setEnabled(enabled)
        self.unknown_count.setEnabled(enabled)
        self.suffix_input.setEnabled(enabled)
        self.custom_pattern_input.setEnabled(enabled)
        self.add_unknown_slot_button.setEnabled(enabled)
        self.edit_selected_slot_button.setEnabled(bool(enabled and self.custom_pattern_input.text().strip()))
        self.use_global_charset_checkbox.setEnabled(enabled)
        self.custom_group.setEnabled(enabled)
        self.custom_tab.setEnabled(enabled)

    def update_encryption_status(self):
        if not self.pdf_path:
            self.encryption_label.setText("Encryption: not checked")
            self.set_guess_controls_enabled(False)
            return

        result = self.detect_encryption_type(self.pdf_path)
        self.encryption_label.setText(result["message"])
        self.set_guess_controls_enabled(result.get("matched", False))

    def select_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select PDF",
            "",
            "PDF Files (*.pdf)"
        )

        if path:
            self.pdf_path = path
            self.file_label.setText(path)
            self.update_encryption_status()
            self.refresh_cpu_summary()

    def toggle_password_visibility(self):
        if self.password.echoMode() == QLineEdit.Password:
            self.password.setEchoMode(QLineEdit.Normal)
            self.show_password_button.setText("\ue8f5")
            self.show_password_button.setToolTip("Hide password")
        else:
            self.password.setEchoMode(QLineEdit.Password)
            self.show_password_button.setText("\ue8f4")
            self.show_password_button.setToolTip("Show password")

    def verify_password(self):
        if not self.pdf_path:
            QMessageBox.warning(self, "Error", "Please select a PDF first.")
            return

        password = self.password.text()

        try:
            valid = check_password(self.pdf_path, password)

            if valid:
                QMessageBox.information(self, "Success", "Password is correct.")
            else:
                QMessageBox.warning(self, "Failed", "Incorrect password.")

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def character_set_for_search(self):
        return build_character_set(
            lowercase=self.lowercase.isChecked(),
            uppercase=self.uppercase.isChecked(),
            numbers=self.numbers.isChecked(),
            symbols=self.symbols.isChecked(),
            custom_chars=self.custom.text(),
        )

    def search_space_size(self):
        charset = self.character_set_for_search()
        if not charset:
            return 0
        unknown_count = max(0, self.unknown_count.value())
        if unknown_count <= 0:
            return 1
        return len(charset) ** unknown_count

    def estimate_guess_time(self):
        if not self.pdf_path:
            return None

        charset = self.character_set_for_search()
        if not charset:
            return None

        search_space = self.search_space_size()
        if search_space <= 0:
            return None

        unknown_count = max(0, self.unknown_count.value())
        prefix = self.prefix_input.text()
        suffix = self.suffix_input.text()
        sample_passwords = []

        if unknown_count <= 0:
            sample_passwords = [f"{prefix}{suffix}"]
        else:
            chars = charset[: min(8, len(charset))]
            for ch in chars:
                sample_passwords.append(f"{prefix}{ch * unknown_count}{suffix}")

        if not sample_passwords:
            return None

        start = time.perf_counter()
        for password in sample_passwords:
            try:
                check_password(self.pdf_path, password)
            except Exception:
                pass
        elapsed = time.perf_counter() - start

        throughput = len(sample_passwords) / max(elapsed, 0.001)
        if throughput <= 0:
            return None

        chosen_workers = max(1, int(self.process_count.value() or 1))
        return (search_space / (throughput * chosen_workers))

    def recommended_worker_count(self):
        cpu_count = os.cpu_count() or 1
        charset = self.character_set_for_search()
        if not charset:
            return 1

        search_space = self.search_space_size()
        if search_space <= 1_000:
            return 1
        if search_space <= 10_000:
            return min(2, cpu_count)
        if search_space <= 1_000_000:
            return min(3, cpu_count)
        if search_space <= 10_000_000:
            return min(4, cpu_count)
        if search_space <= 100_000_000:
            return min(6, cpu_count)
        return min(8, cpu_count)

    def recommend_workers_for_search(self):
        charset = self.character_set_for_search()
        if not charset:
            QMessageBox.warning(self, "Search criteria", "Please enable at least one character set before recommending workers.")
            return

        search_space = self.search_space_size()
        recommended = self.recommended_worker_count()
        chosen = max(1, min(self.process_count.value(), os.cpu_count() or 1))
        self.process_count.setValue(recommended)
        self.refresh_cpu_summary()

        if search_space <= 1_000:
            detail = "very small search space, so 1 worker is enough and avoids process overhead."
        elif search_space <= 1_000_000:
            detail = "moderate search space, so a few workers help without much extra overhead."
        elif search_space <= 10_000_000:
            detail = "large search space, so parallel workers improve throughput noticeably."
        else:
            detail = "very large search space, so multiple workers are worth using to reduce total runtime."

        self.worker_recommendation_label.setText(
            f"Recommended workers: {recommended}\n"
            f"Reason: {detail}\n"
            f"Criteria: {self.unknown_count.value()} unknowns, {len(charset)} chars, search size {search_space:,}.\n"
            f"Current choice: {chosen}."
        )

    def refresh_cpu_summary(self):
        cpu_count = os.cpu_count() or 1
        workers = max(1, self.process_count.value())
        suggested = self.recommended_worker_count()
        self.process_count.setValue(min(workers, max(1, cpu_count)))
        usage = min(100, round((workers / cpu_count) * 100)) if cpu_count else 0

        estimated_seconds = self.estimate_guess_time() if self.pdf_path else None
        if estimated_seconds is not None:
            minutes = estimated_seconds / 60
            hours = minutes / 60
            days = hours / 24
            if days >= 1:
                runtime_text = f"{days:.1f} days"
            elif hours >= 1:
                runtime_text = f"{hours:.1f} hours"
            elif minutes >= 1:
                runtime_text = f"{minutes:.1f} minutes"
            else:
                runtime_text = f"{estimated_seconds:.0f} seconds"
            self.runtime_estimate_label.setText(f"Estimated runtime before guess: {runtime_text}")
        else:
            self.runtime_estimate_label.setText("Estimated runtime before guess: unavailable")

        self.cpu_usage_label.setText(
            f"CPU estimate: {usage}% ({workers}/{cpu_count} workers used; recommended: {suggested})"
        )
        search_space = self.search_space_size()
        if search_space > 0:
            if search_space <= 1_000:
                reason = "Very small search space: one worker avoids unnecessary multiprocessing overhead."
            elif search_space <= 1_000_000:
                reason = "Moderate search space: a few workers can help without much efficiency loss."
            elif search_space <= 10_000_000:
                reason = "Large search space: more workers improve throughput and reduce runtime."
            else:
                reason = "Very large search space: parallel workers are recommended to keep the search practical."
            self.worker_recommendation_label.setText(
                f"Recommended workers: {suggested}\n"
                f"Reason: {reason}\n"
                f"Criteria: {self.unknown_count.value()} unknowns, {len(self.character_set_for_search())} chars, space {search_space:,}."
            )
        else:
            self.worker_recommendation_label.setText(
                f"Recommended workers: {suggested}\n"
                f"Reason: More workers can help, but the search space is too small to benefit much from parallelism."
            )

    def update_progress(self, tried, total, worker_progress=None):
        self._last_tried_count = max(0, int(tried))
        self._last_worker_progress = worker_progress or {}
        if total <= 0:
            text = "Progress: 0 / 0\nElapsed: 00:00:00\nSpeed: 0 /s (0 /min)\nETA: --\nFinish: --"
            self.progress_label.setText(text)
            self.worker_progress_label.setText("Worker progress: none")
            QApplication.processEvents()
            return

        if worker_progress:
            lines = []
            for key in sorted(worker_progress.keys(), key=lambda item: int(item.split("_")[-1])):
                entry = worker_progress[key]
                if len(entry) == 2:
                    current_index, total_range = entry
                    assigned_start = 0
                    assigned_end = max(0, total_range - 1)
                else:
                    current_index, total_range, assigned_start, assigned_end = entry[:4]

                lines.append(
                    f"{key}: index {current_index}/{total_range} "
                    f"(assigned {assigned_start}–{assigned_end})"
                )
            self.worker_progress_label.setText("Worker progress:\n" + "\n".join(lines))
        else:
            self.worker_progress_label.setText("Worker progress: idle")

        elapsed_seconds = max((QDateTime.currentMSecsSinceEpoch() - self._progress_started_at) / 1000.0, 0.001)
        guesses_per_second = tried / elapsed_seconds
        guesses_per_minute = guesses_per_second * 60
        remaining = max(total - tried, 0)
        remaining_seconds = remaining / guesses_per_second if guesses_per_second > 0 else 0

        def format_duration(seconds):
            total_seconds = int(seconds)
            hours, remainder = divmod(total_seconds, 3600)
            minutes, secs = divmod(remainder, 60)
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"

        def format_eta(seconds):
            if seconds <= 0:
                return "now"
            minutes = seconds / 60
            hours = minutes / 60
            days = hours / 24

            if days >= 1:
                return f"{days:.1f} days"
            if hours >= 1:
                return f"{hours:.1f} hours"
            if minutes >= 1:
                return f"{minutes:.1f} minutes"
            return f"{seconds:.0f} seconds"

        finish_time_ms = self._progress_started_at + int(remaining_seconds * 1000) + int(elapsed_seconds * 1000)
        finish_time = QDateTime.fromMSecsSinceEpoch(finish_time_ms)

        text = (
            f"Progress: {tried} / {total} ({(tried / total * 100):.1f}%)\n"
            f"Elapsed: {format_duration(elapsed_seconds)}\n"
            f"Speed: {guesses_per_second:.1f} /s ({guesses_per_minute:.1f} /min)\n"
            f"ETA: {format_eta(remaining_seconds)}\n"
            f"Finish: {finish_time.toString('yyyy-MM-dd hh:mm:ss')}"
        )
        self.progress_label.setText(text)
        QApplication.processEvents()

    def _wait_for_clean_guess_shutdown(self, timeout_ms=5000):
        if not self._guess_thread:
            self.thread_status_label.setText("Thread status: ready")
            return True

        if not self._guess_thread.isRunning():
            self.thread_status_label.setText("Thread status: ready")
            return True

        self.thread_status_label.setText("Thread status: waiting for clean shutdown...")
        self._guess_thread.wait(timeout_ms)
        status = "ready" if not self._guess_thread.isRunning() else "still shutting down"
        self.thread_status_label.setText(f"Thread status: {status}")
        QApplication.processEvents()
        return False

    def _build_current_checkpoint(self):
        current_tab = self.findChild(QTabWidget)
        custom_pattern = self.custom_pattern_input.text().strip() if current_tab and current_tab.currentIndex() == 1 else ""

        worker_id = "worker_0"
        last_processed_index = max(0, self._last_tried_count)
        worker_progress = {}

        if self._last_worker_progress:
            worker_progress = {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in self._last_worker_progress.items()
            }
            worker_scores = {}
            for key, value in worker_progress.items():
                if not value:
                    continue
                if len(value) >= 4:
                    current_index = value[0]
                elif len(value) == 2:
                    current_index = value[0]
                else:
                    continue
                worker_scores[key] = current_index
            if worker_scores:
                worker_id = max(worker_scores, key=worker_scores.get)
                last_processed_index = max(worker_scores.values(), default=last_processed_index)

        checkpoint = {
            "mode": "custom_pattern" if custom_pattern else "standard",
            "pdf_path": self.pdf_path,
            "prefix": self.prefix_input.text(),
            "suffix": self.suffix_input.text(),
            "unknown_count": self.unknown_count.value(),
            "lowercase": self.lowercase.isChecked(),
            "uppercase": self.uppercase.isChecked(),
            "numbers": self.numbers.isChecked(),
            "symbols": self.symbols.isChecked(),
            "custom_chars": self.custom.text(),
            "custom_pattern": custom_pattern,
            "process_count": self.process_count.value(),
            "tried": max(0, self._last_tried_count),
            "next_index": max(0, last_processed_index + 1),
            "last_candidate": self._last_candidate,
            "last_worker_id": worker_id,
            "last_processed_index": last_processed_index,
            "worker_progress": worker_progress,
            "status": "paused",
        }
        return checkpoint

    def _show_pause_controls(self):
        self._checkpoint = self._build_current_checkpoint()
        self.continue_pause_button.show()
        self.save_pause_button.show()
        self.pause_controls_widget.show()
        self.pause_controls_widget.raise_()
        self.pause_button.hide()
        self.stop_guess_button.show()
        self.update()
        QApplication.processEvents()

    def _hide_pause_controls(self):
        self.continue_pause_button.hide()
        self.save_pause_button.hide()
        self.pause_controls_widget.hide()
        self.pause_button.show()
        self.stop_guess_button.show()
        self.update()
        QApplication.processEvents()

    def _apply_checkpoint_to_form(self, checkpoint):
        if not checkpoint:
            return

        self.prefix_input.setText(str(checkpoint.get("prefix", self.prefix_input.text())))
        self.suffix_input.setText(str(checkpoint.get("suffix", self.suffix_input.text())))
        self.unknown_count.setValue(int(checkpoint.get("unknown_count", self.unknown_count.value())))
        self.process_count.setValue(max(1, int(checkpoint.get("process_count", self.process_count.value()))))

        self.lowercase.setChecked(bool(checkpoint.get("lowercase", self.lowercase.isChecked())))
        self.uppercase.setChecked(bool(checkpoint.get("uppercase", self.uppercase.isChecked())))
        self.numbers.setChecked(bool(checkpoint.get("numbers", self.numbers.isChecked())))
        self.symbols.setChecked(bool(checkpoint.get("symbols", self.symbols.isChecked())))
        self.custom.setText(str(checkpoint.get("custom_chars", self.custom.text())))

        custom_pattern = checkpoint.get("custom_pattern", "")
        if custom_pattern:
            self.custom_pattern_input.setText(str(custom_pattern))
            self.use_global_charset_checkbox.setChecked(True)

        current_tab = self.findChild(QTabWidget)
        if current_tab is not None and checkpoint.get("mode") == "custom_pattern":
            current_tab.setCurrentIndex(1)

        self.refresh_cpu_summary()

    def _validate_checkpoint_pdf(self, checkpoint):
        if checkpoint is None:
            return True
        if checkpoint_matches_pdf(checkpoint, self.pdf_path):
            return True

        checkpoint_pdf = checkpoint.get("pdf_path") or "unknown"
        QMessageBox.warning(
            self,
            "Checkpoint PDF mismatch",
            f"This checkpoint was saved for:\n{checkpoint_pdf}\n\nCurrent PDF:\n{self.pdf_path or 'none selected'}\n\nPlease select the same PDF before continuing.",
        )
        return False

    def load_saved_checkpoint(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open saved checkpoint", "", "JSON Files (*.json)")
        if not file_name:
            return

        try:
            checkpoint = load_checkpoint_from_json(file_name)
        except Exception as exc:
            QMessageBox.critical(self, "Checkpoint load failed", f"Could not open checkpoint: {exc}")
            return

        if not isinstance(checkpoint, dict):
            QMessageBox.warning(self, "Invalid checkpoint", "The selected file is not a valid checkpoint JSON.")
            return

        if self.pdf_path and not checkpoint_matches_pdf(checkpoint, self.pdf_path):
            QMessageBox.warning(
                self,
                "Checkpoint PDF mismatch",
                f"This checkpoint belongs to:\n{checkpoint.get('pdf_path') or 'unknown'}\n\nCurrent PDF:\n{self.pdf_path}\n\nPlease load the matching PDF first.",
            )
            return

        if not self.pdf_path and checkpoint.get("pdf_path"):
            self.pdf_path = checkpoint["pdf_path"]
            self.file_label.setText(self.pdf_path)
            self.update_encryption_status()

        self._checkpoint = checkpoint
        self._last_tried_count = int(checkpoint.get("tried", 0) or 0)
        self._last_candidate = checkpoint.get("last_candidate", "")
        self._last_worker_progress = checkpoint.get("worker_progress", {}) or {}
        self._apply_checkpoint_to_form(checkpoint)
        self._show_pause_controls()
        self.append_log(f"Loaded checkpoint from {file_name} for PDF {self.pdf_path or checkpoint.get('pdf_path')}.")
        self.thread_status_label.setText("Thread status: checkpoint loaded")

    def continue_from_pause(self):
        if not self._validate_checkpoint_pdf(self._checkpoint):
            return

        self._is_paused = False
        resume_guessing()
        self._hide_pause_controls()
        self.append_log(f"Continuing paused search from attempt {self._checkpoint.get('tried', self._last_tried_count) if self._checkpoint else self._last_tried_count}.")
        self.start_guess_worker(resume_session=self._checkpoint)

    def save_pause_checkpoint(self):
        if not self._validate_checkpoint_pdf(self._checkpoint):
            return

        self._is_paused = False
        self._checkpoint = self._build_current_checkpoint()
        file_name, _ = QFileDialog.getSaveFileName(self, "Save checkpoint as JSON", "guess-session.json", "JSON Files (*.json)")
        if file_name:
            save_checkpoint_to_json(self._checkpoint, file_name)
        self.thread_status_label.setText("Thread status: saved checkpoint")
        self.guess_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.stop_guess_button.setEnabled(False)
        clear_guess_stop()
        clear_session_checkpoint()
        self._checkpoint = None
        self._hide_pause_controls()
        self.pause_button.show()

    def _offer_pause_options(self):
        self._show_pause_controls()

    def _worker_status_summary(self):
        if not self._last_worker_progress:
            return "worker summary unavailable"

        parts = []
        for key in sorted(self._last_worker_progress.keys(), key=lambda item: int(item.split("_")[-1])):
            entry = self._last_worker_progress[key]
            if not entry:
                continue
            if len(entry) >= 4:
                current_index, total_range, assigned_start, assigned_end = entry[:4]
            elif len(entry) == 2:
                current_index, total_range = entry
                assigned_start = 0
                assigned_end = max(0, total_range - 1)
            else:
                continue
            parts.append(f"{key}: index {current_index}/{total_range} (assigned {assigned_start}–{assigned_end})")

        return "; ".join(parts) if parts else "worker summary unavailable"

    def append_log(self, text, clear=False):
        if clear:
            self.log_output.clear()
        timestamp = QTime.currentTime().toString("hh:mm:ss")
        self.log_output.append(f"[{timestamp}] {text}")
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())
        QApplication.processEvents()

    def log_search_criteria(self):
        prefix = self.prefix_input.text()
        suffix = self.suffix_input.text()
        charset = self.character_set_for_search()
        workers = max(1, self.process_count.value())
        custom_pattern = self.custom_pattern_input.text().strip() if self.findChild(QTabWidget) and self.findChild(QTabWidget).currentIndex() == 1 else ""
        summary = (
            f"Search criteria: prefix='{prefix}', unknowns={self.unknown_count.value()}, suffix='{suffix}', "
            f"charset_size={len(charset)}, workers={workers}, custom_pattern={custom_pattern or 'standard'}"
        )
        self.append_log(summary)

    def _guess_finished(self, result):
        if self._is_paused:
            self._guess_in_progress = False
            self.guess_button.setEnabled(True)
            self.pause_button.setEnabled(False)
            self.stop_guess_button.setEnabled(False)
            self.thread_status_label.setText("Thread status: paused")
            checkpoint = self._checkpoint or current_checkpoint() or {}
            last_worker = checkpoint.get("last_worker_id", "unknown")
            last_index = checkpoint.get("last_processed_index", self._last_tried_count)
            self.append_log(
                f"Paused run retained at {self._last_tried_count} attempts. "
                f"Last worker: {last_worker}; last processed index: {last_index}."
            )
            return

        self._guess_in_progress = False
        self.guess_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.stop_guess_button.setEnabled(False)
        self._hide_pause_controls()
        self.thread_status_label.setText("Thread status: ready")
        clear_guess_stop()
        resume_guessing()

        elapsed_seconds = 0
        if self._search_started_at is not None:
            elapsed_seconds = max((QDateTime.currentMSecsSinceEpoch() - self._search_started_at) / 1000.0, 0)

        speed_per_second = self._last_tried_count / max(elapsed_seconds, 0.001)
        speed_per_minute = speed_per_second * 60

        worker_summary = self._worker_status_summary()
        result_password = result
        worker_id = "unknown"
        last_index = self._last_tried_count
        attempts = self._last_tried_count

        if isinstance(result, dict):
            result_password = result.get("password")
            worker_id = result.get("worker_id", worker_id)
            last_index = result.get("index", last_index)
            attempts = result.get("attempts", attempts)
        elif isinstance(result, str):
            worker_id = self._last_worker_progress and next(
                (key for key, value in self._last_worker_progress.items() if value and value[0] >= max(0, self._last_tried_count - 1)),
                "unknown",
            ) or "unknown"

        if worker_id == "unknown" and self._last_worker_progress:
            worker_id = next(iter(self._last_worker_progress.keys()), "unknown")

        if result_password:
            self.password.setText(str(result_password))
            self.append_log(
                f"Search finished: password found by {worker_id} after {attempts} local attempts "
                f"in {elapsed_seconds:.1f}s (speed {speed_per_second:.1f}/s, {speed_per_minute:.1f}/min) "
                f"using {worker_summary}."
            )
            QMessageBox.information(self, "Success", f"Password found: {result_password}")
        elif self._guess_was_cancelled:
            self.append_log(
                f"Search stopped by user after {self._last_tried_count} attempts "
                f"in {elapsed_seconds:.1f}s (speed {speed_per_second:.1f}/s, {speed_per_minute:.1f}/min) "
                f"using {worker_summary}."
            )
            QMessageBox.warning(self, "Stopped", "Password guessing was stopped by the user.")
        else:
            self.append_log(
                f"Search finished: no match found after {self._last_tried_count} attempts "
                f"in {elapsed_seconds:.1f}s (speed {speed_per_second:.1f}/s, {speed_per_minute:.1f}/min) "
                f"using {worker_summary}."
            )
            QMessageBox.warning(self, "Not found", "No match found for the given pattern.")

    def _guess_paused(self, checkpoint):
        self._is_paused = True
        self._guess_in_progress = False
        self.guess_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.stop_guess_button.setEnabled(False)
        self._checkpoint = checkpoint or current_checkpoint() or self._build_current_checkpoint()
        self.thread_status_label.setText("Thread status: paused")
        last_worker = self._checkpoint.get("last_worker_id", "unknown")
        last_index = self._checkpoint.get("last_processed_index", self._last_tried_count)
        self.append_log(
            f"Search paused at {self._last_tried_count} attempts. "
            f"Last worker: {last_worker}; last processed index: {last_index}. Use Continue or Save JSON."
        )
        self._show_pause_controls()

    def _guess_error(self, message):
        self._guess_in_progress = False
        self.guess_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.stop_guess_button.setEnabled(False)
        self._hide_pause_controls()
        self.thread_status_label.setText("Thread status: ready")
        clear_guess_stop()
        resume_guessing()
        QMessageBox.critical(self, "Error", message)

    def pause_guess(self):
        if not self._guess_thread or not self._guess_thread.isRunning():
            return

        self._is_paused = True
        self._checkpoint = self._build_current_checkpoint()
        self.pause_button.setEnabled(False)
        self.thread_status_label.setText("Thread status: pausing...")
        self.append_log("Pause requested. Worker will stop at the next safe checkpoint.")
        self._show_pause_controls()
        QApplication.processEvents()
        pause_guessing()

    def stop_guess(self):
        if self._guess_thread and self._guess_thread.isRunning():
            self._guess_was_cancelled = True
            self._is_paused = False
            self.stop_guess_button.setEnabled(False)
            self.pause_button.setEnabled(False)
            self._hide_pause_controls()
            self.thread_status_label.setText("Thread status: stopping...")
            QApplication.processEvents()
            stop_guessing()
            self._wait_for_clean_guess_shutdown(5000)

    def start_guess_worker(self, resume_session=None):
        clear_guess_stop()
        resume_guessing()
        self._is_paused = False
        self._hide_pause_controls()
        self._guess_was_cancelled = False
        self._guess_in_progress = True
        self._search_started_at = QDateTime.currentMSecsSinceEpoch()
        self.thread_status_label.setText("Thread status: running")
        self._progress_started_at = self._search_started_at
        self.progress_label.setText("Progress: 0 / 0\nElapsed: 00:00:00\nSpeed: 0 /s (0 /min)\nETA: --\nFinish: --")
        self.worker_progress_label.setText("Worker progress: starting...")
        self.guess_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.pause_button.show()
        self.stop_guess_button.setEnabled(True)

        if resume_session is not None:
            self._last_tried_count = int(resume_session.get("tried", self._last_tried_count) or 0)
            self._last_candidate = resume_session.get("last_candidate", self._last_candidate)
            self._last_worker_progress = resume_session.get("worker_progress", self._last_worker_progress) or {}
            self.append_log(
                f"Resuming paused search from attempt {self._last_tried_count} "
                f"(next_index={resume_session.get('next_index', self._last_tried_count)}) ."
            )
        else:
            self.append_log("Starting new search.")
            self.log_search_criteria()

        recommended = self.recommended_worker_count()
        chosen_workers = self.process_count.value()
        if chosen_workers == 0:
            chosen_workers = recommended
        if chosen_workers > recommended and chosen_workers > 2 and recommended <= 2:
            self.worker_recommendation_label.setText(
                f"Recommended workers: {recommended} | high workers can reduce speed due to process overhead"
            )

        self._guess_thread = QThread(self)
        current_tab = self.findChild(QTabWidget)
        custom_pattern = self.custom_pattern_input.text().strip() if current_tab and current_tab.currentIndex() == 1 else ""

        self._guess_worker = GuessWorker(
            self.pdf_path,
            prefix=self.prefix_input.text(),
            unknown_count=self.unknown_count.value(),
            suffix=self.suffix_input.text(),
            lowercase=self.lowercase.isChecked(),
            uppercase=self.uppercase.isChecked(),
            numbers=self.numbers.isChecked(),
            symbols=self.symbols.isChecked(),
            custom_chars=self.custom.text(),
            process_count=chosen_workers,
            custom_pattern=custom_pattern,
            resume_session=resume_session,
        )
        self._guess_worker.moveToThread(self._guess_thread)
        self._guess_thread.started.connect(self._guess_worker.run)
        self._guess_worker.progress.connect(self.update_progress)
        self._guess_worker.finished.connect(self._guess_finished)
        self._guess_worker.paused.connect(self._guess_paused)
        self._guess_worker.finished.connect(self._guess_thread.quit)
        self._guess_worker.paused.connect(self._guess_thread.quit)
        self._guess_worker.error.connect(self._guess_error)
        self._guess_worker.error.connect(self._guess_thread.quit)
        self._guess_thread.finished.connect(self._guess_worker.deleteLater)
        self._guess_thread.start()

    def guess_pattern_password(self):
        if not self.pdf_path:
            QMessageBox.warning(self, "Error", "Please select a PDF first.")
            return

        if self._guess_thread and self._guess_thread.isRunning():
            self.thread_status_label.setText("Thread status: waiting for clean shutdown...")
            QApplication.processEvents()
            return

        self.start_guess_worker()


def main():
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()