"""The accounts, read from the data warehouse (SQL Server) instead of an Excel export.

  accounts(source, refresh=False)   the accounts of "zoominfo" or "crm", as a table

Each source is a query in queries/ (zoominfo.sql, crm.sql). The first time, or when refresh=True, the query runs once
and its result is saved as a snapshot: data/snapshots/<source>_<date>_<time>.csv. Every other time the latest snapshot
is used, so all the steps of a run work from the same accounts and the warehouse is read once per refresh. Refresh to
pick up new accounts, changed websites and accounts that went inactive.

The connection is read only, with your Windows login (no password). It needs the "ODBC Driver 18 for SQL Server"
(installed with SQL Server tools) and pip install pyodbc.
"""
from datetime import datetime
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

FOLDER = Path(__file__).parent
QUERIES = FOLDER / "queries"
SNAPSHOTS = FOLDER / "data" / "snapshots"
load_dotenv(FOLDER / ".env")
SERVER = os.getenv("DWH_SERVER", "")  # the development data warehouse; in .env, kept out of the repo
DATABASE = "DataWarehouse"
DRIVER = "ODBC Driver 18 for SQL Server"


def connect():
    """A read-only connection with your Windows login. TrustServerCertificate: the server's certificate is an internal
    one that Windows doesn't know; drop it once IT makes the certificate trusted on this machine."""
    import pyodbc
    if not SERVER:
        raise RuntimeError("Set DWH_SERVER in .env (see .env.example).")
    return pyodbc.connect(f"Driver={{{DRIVER}}};Server={SERVER};Database={DATABASE};Trusted_Connection=yes;"
                          "Encrypt=yes;TrustServerCertificate=yes;", timeout=30, readonly=True)


def latest_snapshot(source):
    """The newest snapshot file of a source, or None."""
    files = sorted(SNAPSHOTS.glob(f"{source}_*.csv"))
    return files[-1] if files else None


def fetch(source):
    """Run the source's query and save the result as a new snapshot. Returns the snapshot's path."""
    query = (QUERIES / f"{source}.sql").read_text(encoding="utf-8")
    with connect() as conn:
        table = pd.read_sql(query, conn)
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS / f"{source}_{datetime.now():%Y-%m-%d_%H%M}.csv"
    table.to_csv(path, index=False, encoding="utf-8")
    print(f"{source}: {len(table):,} accounts from the data warehouse -> {path.name}")
    return path


def accounts(source, refresh=False):
    """The accounts of a source, as text columns (the same columns as the queries). Uses the latest snapshot unless
    refresh=True or there is none yet."""
    path = latest_snapshot(source)
    if refresh or path is None:
        path = fetch(source)
    else:
        print(f"{source}: using the snapshot {path.name} (refresh=True fetches the accounts again)")
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
