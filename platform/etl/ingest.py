"""Discover, dedupe and parse the raw platform exports.

Handles the three structural facts of this dataset:
  * identical files saved under several folders  -> content-hash dedup
  * 0-6 lines of preamble before the real header -> header-row sniffing
  * one workbook holding differently-shaped tabs -> every sheet tried separately
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from etl.signatures import Signature, detect

MAX_HEADER_SCAN = 12
CATEGORIES = {
    "instant coffee": "Instant Coffee",
    "filter coffee": "Filter Coffee",
    "cold coffee": "Cold Coffee",
}
DATA_SUFFIXES = {".csv", ".xlsx", ".xls", ".zip"}


@dataclass
class Dataset:
    """One detected table: a file+sheet that matched a signature."""
    path: Path
    sha256: str
    sheet_name: str
    signature: Optional[Signature]
    df: Optional[pd.DataFrame]
    raw_rows: list = field(default_factory=list)
    category: Optional[str] = None
    sub_platform: Optional[str] = None
    ad_type: Optional[str] = None
    campaign_name_hint: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    status: str = "ok"          # ok | needs_review | duplicate | failed
    error: Optional[str] = None
    # What the person uploading said this file was. Columns still decide the
    # answer; this only fills the gap when nothing matches, and flags disagreement.
    declared_platform: Optional[str] = None

    @property
    def filename(self) -> str:
        return self.path.name


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _sheets(path: Path) -> dict[str, list[list[str]]]:
    """Return {sheet_name: rows-as-lists-of-strings}. CSV yields one pseudo-sheet.

    Everything is read as text so '₹ 3,09,832.39' and '29.19%' survive intact —
    normalize.py owns all type coercion.
    """
    suffix = path.suffix.lower()
    if suffix == ".csv":
        # csv module rather than pandas: preamble lines have inconsistent widths
        # and would otherwise blow up or silently drop data rows.
        rows = list(csv.reader(io.StringIO(_read_text(path))))
        return {"<csv>": rows}

    out = {}
    book = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
    for name, frame in book.items():
        out[name] = frame.where(frame.notna(), None).values.tolist()
    return out


def _find_header(rows: list[list]) -> tuple[Optional[int], Optional[Signature]]:
    """Scan the top rows for the one that looks like a header a signature knows."""
    for i, row in enumerate(rows[:MAX_HEADER_SCAN]):
        if not row:
            continue
        sig = detect([c for c in row if c not in (None, "")])
        if sig:
            return i, sig
    return None, None


def _frame(rows: list[list], header_row: int) -> pd.DataFrame:
    # Blank header cells get a positional name (BigBasket's product exports leave the
    # product-name column header empty), so they stay addressable and don't collide.
    header = [
        (str(c).strip() if c is not None and str(c).strip() else f"col {i}")
        for i, c in enumerate(rows[header_row])
    ]
    width = len(header)
    body = []
    for r in rows[header_row + 1:]:
        r = list(r)[:width] + [None] * max(0, width - len(r))
        if all(c is None or str(c).strip() == "" for c in r):
            continue
        body.append(r)
    df = pd.DataFrame(body, columns=header)
    # duplicate/blank header names would collide on rename; keep the first
    return df.loc[:, ~pd.Index(df.columns).duplicated()]


_DATE_IN_NAME = re.compile(r"R\((\d{8})-(\d{8})\)")
_PREAMBLE_KEYS = {
    "start": ("start time", "from date", "start date"),
    "end": ("end time", "to date", "end date"),
}


def _parse_date(value) -> Optional[date]:
    if value in (None, "", "NA"):
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y%m%d",
                "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(text[:len(fmt) + 4].strip(), fmt).date()
        except ValueError:
            continue
    try:
        return pd.to_datetime(text, dayfirst=True).date()
    except Exception:
        return None


def _period(path: Path, rows: list[list], header_row: int):
    """Reporting period from the filename token or the preamble rows above the header."""
    m = _DATE_IN_NAME.search(path.name)
    if m:
        return _parse_date(m.group(1)), _parse_date(m.group(2))

    start = end = None
    for row in rows[:header_row]:
        if not row or row[0] is None:
            continue
        label = str(row[0]).strip().lower()
        value = next((c for c in row[1:] if c not in (None, "")), None)
        if value is None:
            continue
        if any(label.startswith(k) for k in _PREAMBLE_KEYS["start"]):
            start = _parse_date(value)
        elif any(label.startswith(k) for k in _PREAMBLE_KEYS["end"]):
            end = _parse_date(value)
    return start, end


# Short variant tags used in export filenames (…City Wise IC.csv). Matched only as
# whole words so they can't fire inside "classic", "graphic", etc.
_CATEGORY_ABBREV = {"ic": "Instant Coffee", "fc": "Filter Coffee", "cc": "Cold Coffee"}


def _category_from_path(path: Path) -> Optional[str]:
    text = str(path).lower()
    for needle, label in CATEGORIES.items():
        if needle in text or needle.replace(" ", "") in text.replace(" ", ""):
            return label
    for tag, label in _CATEGORY_ABBREV.items():
        if re.search(rf"\b{tag}\b", text):
            return label
    return None


def _sub_platform_from_path(path: Path) -> Optional[str]:
    text = str(path).lower()
    if "minute" in text:
        return "Minutes"
    if "national" in text or "filpkart national" in text:
        return "National"
    return None


_PLATFORM_NAMES = ("Amazon", "Flipkart", "Zepto", "Instamart", "BigBasket", "Blinkit")


def _platform_from_path(path: Path) -> Optional[str]:
    """The platform a file's folder implies — used only to flag misfiling, never to
    classify (columns decide that)."""
    low = str(path).lower()
    for p in _PLATFORM_NAMES:
        if p.lower() in low:
            return p
    return None


def _sub_platform_from_channel(df) -> Optional[str]:
    """Flipkart campaign exports carry the fulfilment channel in an unnamed column —
    HYPERLOCAL = Minutes, FLIPKART = National. Reading it lets an uploaded campaign
    file self-classify without relying on the folder path. (Dormant rows show '0',
    so we look for the presence of either token across the sheet.)"""
    if df is None:
        return None
    vals = {str(v).strip().upper() for v in df.to_numpy().ravel()}
    if "HYPERLOCAL" in vals:
        return "Minutes"
    if "FLIPKART" in vals:
        return "National"
    return None


def _flipkart_sub_platform(sig, df, path) -> Optional[str]:
    """Channel column first (self-describing), folder path as fallback."""
    if sig.report_type == "campaign":
        channel = _sub_platform_from_channel(df)
        if channel:
            return channel
    return _sub_platform_from_path(path)


MANIFEST = "_manifest.json"


def _declared(input_dir: Path, key: str) -> dict:
    """filename -> a value the uploader stated (platform or category).

    The app copies uploads into a timestamped folder and then rescans the whole
    input directory, so the declaration has to live on disk beside the files
    rather than being passed through the call.
    """
    import json

    out = {}
    for manifest in Path(input_dir).rglob(MANIFEST):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        value = data.get(key)
        if not value:
            continue
        for name in data.get("files", []):
            out[(manifest.parent / name).resolve()] = value
    return out


def declared_platforms(input_dir: Path) -> dict:
    return _declared(input_dir, "platform")


def declared_categories(input_dir: Path) -> dict:
    return _declared(input_dir, "category")


def declared_sub_platforms(input_dir: Path) -> dict:
    return _declared(input_dir, "sub_platform")


def declared_ad_types(input_dir: Path) -> dict:
    return _declared(input_dir, "ad_type")


def discover(input_dir: Path, workdir: Path) -> list[Path]:
    """All data files under input_dir, with any zips expanded into workdir."""
    files = []
    for p in sorted(Path(input_dir).rglob("*")):
        if not p.is_file() or p.suffix.lower() not in DATA_SUFFIXES:
            continue
        if p.name.startswith("~$"):
            continue
        if p.suffix.lower() == ".zip":
            target = workdir / p.stem
            target.mkdir(parents=True, exist_ok=True)
            try:
                with zipfile.ZipFile(p) as z:
                    z.extractall(target)
                files.extend(discover(target, workdir))
            except zipfile.BadZipFile:
                continue
        else:
            files.append(p)
    return files


def parse_file(path: Path, seen_hashes: dict[str, Path],
               declared: str | None = None,
               declared_category: str | None = None,
               declared_sub: str | None = None,
               declared_ad_type: str | None = None) -> list[Dataset]:
    """Parse one file into zero or more Datasets (one per matching sheet).

    `declared` is the platform the uploader chose. Column signatures remain
    authoritative — a file whose columns say Zepto is Zepto whatever the dropdown
    said — but the declaration is recorded, used when nothing matches, and
    surfaced as a warning when the two disagree.

    `declared_category` is the product the uploader chose. Unlike platform there is
    no column signature for it, so the choice wins outright — it labels every row
    of the file, falling back to path/heuristic detection only when left blank.

    `declared_sub` is the sub-platform (Flipkart Minutes/National, Zepto PLA/PCA).
    It is normally read from the folder path, which an uploaded file does not have,
    so the choice wins when given.
    """
    digest = sha256_of(path)
    if digest in seen_hashes:
        return [Dataset(path=path, sha256=digest, sheet_name="", signature=None, df=None,
                        status="duplicate",
                        error=f"identical content to {seen_hashes[digest].name}")]
    seen_hashes[digest] = path

    try:
        sheets = _sheets(path)
    except Exception as exc:  # unreadable file should not abort the run
        return [Dataset(path=path, sha256=digest, sheet_name="", signature=None, df=None,
                        status="failed", error=f"{type(exc).__name__}: {exc}")]

    results, matched_any = [], False
    for sheet_name, rows in sheets.items():
        header_row, sig = _find_header(rows)
        if sig is None:
            continue
        matched_any = True
        df = _frame(rows, header_row)
        start, end = _period(path, rows, header_row)
        hint = None
        if sig.campaign_name_above_header and header_row > 0:
            first = rows[header_row - 1]
            hint = str(first[0]).strip() if first and first[0] else None
        mismatch = None
        if declared and declared != sig.platform:
            mismatch = (f"uploaded as {declared}, but the columns are "
                        f"{sig.platform} {sig.report_type} — using the columns")
        else:
            # Folder says one platform, columns say another: load by columns (correct),
            # but flag the filing so a misplaced export is caught, not silently re-homed.
            folder_plat = _platform_from_path(path)
            if folder_plat and folder_plat != sig.platform:
                mismatch = (f"filed under {folder_plat}, but the columns are "
                            f"{sig.platform} {sig.report_type} — loaded as {sig.platform}")
        results.append(Dataset(
            path=path, sha256=digest, sheet_name=sheet_name, signature=sig, df=df,
            category=declared_category or _category_from_path(path),
            sub_platform=declared_sub or (
                _flipkart_sub_platform(sig, df, path) if sig.platform == "Flipkart" else sig.ad_type),
            ad_type=declared_ad_type,
            campaign_name_hint=hint, period_start=start, period_end=end,
            declared_platform=declared, error=mismatch,
        ))

    if not matched_any:
        results.append(Dataset(
            path=path, sha256=digest, sheet_name=", ".join(sheets), signature=None, df=None,
            status="needs_review", declared_platform=declared,
            error=("no column signature matched"
                   + (f" — uploaded as {declared}; add a Signature for this export "
                      "shape in etl/signatures.py" if declared
                      else " — add a Signature in etl/signatures.py")),
        ))
    return results
