"""Whole pipeline in one command:

    python run_all.py                        # uses INPUT_DIR from .env
    python run_all.py "C:\\path\\to\\exports"  # or an explicit folder
"""
import sys

import config
from analytics import insights
from db.models import get_engine
from etl.run import run
from reports import excel, ppt


def main(input_dir=None):
    run(input_dir)
    engine = get_engine()

    counts = insights.generate(engine)
    print(f"\n--- Intelligence ---\n  " + "\n  ".join(
        f"{k:16} {v}" for k, v in counts.items()))

    workbook, sheets = excel.build(engine)
    deck, slides = ppt.build(engine)
    print(f"\n--- Reports ---\n  {workbook}  ({sheets} sheets)\n  {deck}  ({slides} slides)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
