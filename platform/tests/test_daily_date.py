"""A daily upload's declared date becomes each row's reporting date."""
import tempfile
from datetime import date
from pathlib import Path

from etl.ingest import parse_file

HDR = ("State,Campaign name,Status code,Status,Type,Targeting,Campaign start date,"
       "Campaign end date,Campaign budget amount (converted),Campaign budget amount,"
       "Impressions,Clicks,CTR,Total cost (converted),Total cost,CPC (converted),CPC,"
       "Purchases,Sales (converted),Sales,ROAS,CPM (converted),CPM")
ROW = ('ENABLED,Camp,OK,Delivering,SP,AUTO,08-01-2026,,"1000","1000",1000,50,0.05,'
       '"500","500",10,10,5,"1500","1500",3,50,50')


def _amazon_csv() -> Path:
    p = Path(tempfile.mkdtemp()) / "amazon.csv"
    p.write_text(f"{HDR}\n{ROW}\n", encoding="utf-8")
    return p


def demo():
    # Amazon campaign exports carry no date, so the declared date must drive it.
    ds = parse_file(_amazon_csv(), {}, declared_date="2026-08-04")[0]
    assert ds.period_start == date(2026, 8, 4), ds.period_start
    assert ds.period_end == date(2026, 8, 4), ds.period_end

    # No declared date -> falls back to whatever the file states (here, nothing).
    plain = parse_file(_amazon_csv(), {})[0]
    assert plain.period_start is None, plain.period_start

    print("ok")


if __name__ == "__main__":
    demo()
