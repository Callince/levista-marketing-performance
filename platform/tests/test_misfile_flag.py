"""A file whose columns disagree with its folder loads by columns, but is flagged."""
import tempfile
from pathlib import Path

from etl.ingest import parse_file


def _zepto_city_csv(dirname: str) -> Path:
    d = Path(tempfile.mkdtemp()) / dirname
    d.mkdir(parents=True)
    p = d / "report.csv"
    p.write_text(
        "CityName,CampaignName,Spend,Revenue,Atc,Clicks,Cpm,Impressions,Orders,Roas\n"
        "Chennai,CMP-Instant,100,500,3,20,50,1000,5,5.0\n",
        encoding="utf-8",
    )
    return p


def demo():
    # Zepto-shaped file sitting in a BigBasket folder.
    ds = parse_file(_zepto_city_csv("BigBasket"), {})[0]
    assert ds.signature.platform == "Zepto", ds.signature.platform   # columns win
    assert ds.status == "ok"                                         # still loads
    assert ds.error and "filed under BigBasket" in ds.error, ds.error  # but flagged

    # Same file under the right folder: no flag.
    ok = parse_file(_zepto_city_csv("Zepto"), {})[0]
    assert ok.error is None, ok.error

    print("ok")


if __name__ == "__main__":
    demo()
