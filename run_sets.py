"""Run whole sets without anyone at the keyboard: Phase 1 (crawl) then Phase 2 (classify and report) for each set,
one after the other, with everything printed also written to data/run_logs/.

    python run_sets.py zoominfo_3 crm_100              crawl and classify both sets
    python run_sets.py zoominfo_3 --crawl-only         Phase 1 only
    python run_sets.py crm_100 --classify-only         Phase 2 only (the crawl is already done)

The same calls the notebooks make, with the notebooks' defaults. Safe to stop and start again: crawled sites and
paid answers are on disk, so a re-run picks up where it left off. One set failing doesn't stop the next one.
"""
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import classify
import crawl
import datasets
import questions
import report

LOGS = Path(__file__).parent / "data" / "run_logs"
RETRY_WAIT_MIN = 1  # sites that refused us or didn't answer: tried again after this many minutes (up to 3 tries)


class Tee:
    """Print to the screen and to the log file at once."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for s in self.streams:
            s.write(text)
            s.flush()

    def flush(self):
        for s in self.streams:
            s.flush()


def crawl_set(name, retries):
    f = datasets.files(name)
    try:
        crawl.run(f.input, f.store, retry_wait_min=RETRY_WAIT_MIN, retries=retries)
    finally:  # even when the crawl stopped early: what was crawled is saved and gets classified
        summary = crawl.summary(f.store, f.summary)
        print(summary["status"].value_counts().to_string())


def classify_set(name):
    f = datasets.files(name)
    try:
        classify.run(f.store, f.input, f.answers, f.evidence,
                     on_progress=lambda: report.build(f.store, f.answers, f.report, f.label, f.evidence, f.input))
    finally:
        report.build(f.store, f.answers, f.report, f.label, f.evidence, f.input)


def main(args):
    names = [a for a in args if not a.startswith("--")]
    crawl_it, classify_it = "--classify-only" not in args, "--crawl-only" not in args
    unknown = [n for n in names if n not in datasets.SETS]
    if not names or unknown:
        sys.exit(f"name one or more sets from datasets.SETS {list(datasets.SETS)}" +
                 (f"; unknown: {unknown}" if unknown else ""))
    LOGS.mkdir(parents=True, exist_ok=True)
    log = open(LOGS / f"run_{datetime.now():%Y-%m-%d_%H%M}.log", "w", encoding="utf-8")
    sys.__stdout__.reconfigure(errors="replace")  # a company name the Windows console can't show mustn't stop the run
    sys.stdout = sys.stderr = Tee(sys.__stdout__, log)
    print(f"{datetime.now():%Y-%m-%d %H:%M} | sets {names} | questions version {questions.QUESTIONS_VERSION}")
    # New sites are crawled and classified first, so their results don't wait on the slow retries of sites that
    # failed on earlier runs; those get one quick try at the end, and whatever comes through is classified too.
    # A step that fails is logged and the next step still runs: a crawl that stopped early has saved what it got.
    steps = [("Phase 1 crawl (new sites)", lambda n: crawl_set(n, "skip"), crawl_it),
             ("Phase 2 classify", classify_set, classify_it),
             ("Phase 1 crawl (quick retry of earlier failures)", lambda n: crawl_set(n, "only"), crawl_it),
             ("Phase 2 classify (retried sites)", classify_set, classify_it and crawl_it)]
    for name in names:
        for step, run_step, wanted in steps:
            if not wanted:
                continue
            start = time.perf_counter()
            print(f"\n=== {name}: {step} ===")
            try:
                run_step(name)
                print(f"=== {name}: {step} done in {(time.perf_counter() - start) / 60:.0f} min ===")
            except Exception:  # noqa: BLE001 (logged; the next step still runs)
                print(f"=== {name}: {step} FAILED ===\n{traceback.format_exc()}")
    print(f"\n{datetime.now():%Y-%m-%d %H:%M} | all done")


if __name__ == "__main__":
    main(sys.argv[1:])
