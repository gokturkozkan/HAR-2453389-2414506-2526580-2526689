from pathlib import Path
import sys


TESTS_DIR = Path(__file__).resolve().parent
RASPBERRY_PI_DIR = TESTS_DIR.parent

if str(RASPBERRY_PI_DIR) not in sys.path:
    sys.path.insert(0, str(RASPBERRY_PI_DIR))
