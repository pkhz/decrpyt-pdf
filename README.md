# PDF Password Decrypt / Brute-Force Tool

This project is a local Python desktop app for checking and brute-forcing PDF passwords using a PySide6 GUI. Current limitation is only for encryption Standard/AESV2.

It lets you:
- select a PDF file
- detect whether it is encrypted
- verify a supplied password
- guess passwords by pattern
- pause, save, and continue a search session
- resume from saved checkpoint JSON files

## Requirements

- Python 3.10+
- Windows (project is built around the local Windows workflow)
- Dependencies in requirements.txt

## Local setup

From the project folder (example C:\path):

```cmd
git clone <repo>
cd C:\path
```

Virtual environment:
```
python -m venv .venv
source .venv/Scripts/activate
```

Install dependencies:
```
pip install -r requirements.txt
```

## Run the app

```powershell
python app.py
```

## Main app flow

1. Select a PDF file
2. Click "Verify Password" to test a typed password
3. Choose pattern settings:
   - known prefix
   - unknown length
   - suffix
   - worker count
   - character sets
4. Click "Guess by Pattern"
5. The app searches candidate passwords in parallel and updates progress live
6. You can pause, save a checkpoint, and continue later

## Save / continue workflow

The app supports session persistence:
- Pause the running search
- Save a JSON checkpoint
- Load it later from the app
- Resume from the last valid state without restarting from zero

Checkpoint files are saved as JSON and can be reloaded when the same PDF is selected.

## Project files

- `app.py` — GUI and orchestration logic
- `main.py` — password verification against the PDF
- `combined_pdf.py` — brute-force search logic, checkpoint handling, multiprocessing, and resume logic
- `fonts/` — icon/font assets, currently for hide/show pass icon
- `requirements.txt` — dependencies

## Notes

- Works efficiently with small estimate time if password is partially known eg: passXX. XX is unknown count of letters or numbers.
- Use the same PDF file when loading a checkpoint; mismatches are rejected for safety.
- For large searches, worker count matters. Worker count uses CPU. You can view recommendations.
- Large count workers depends on own CPU limitation. Use at your own CPU limit.

## Brute-force settings recommendation

- Known prefix: empty
- Suffix: empty
- All character sets
- Search unknown digits one by one, eg: 1, search, if not found, 2, and so on.