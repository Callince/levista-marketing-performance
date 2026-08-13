"""Flipkart campaign files self-classify from their columns, not the folder path.

    python -m tests.test_flipkart_selfclassify
"""
import pandas as pd

from etl.ingest import _sub_platform_from_channel
from etl.normalize import normalize
from etl.ingest import Dataset
from etl.signatures import detect


def _channel_col(channel):
    # mirrors the real export: unnamed channel column + a campaign name column
    return pd.DataFrame({"Name": ["FM-PCA-Filter Coffee", "x"],
                         "col 8": [channel, "0"]})


def test_channel_to_sub_platform():
    assert _sub_platform_from_channel(_channel_col("HYPERLOCAL")) == "Minutes"
    assert _sub_platform_from_channel(_channel_col("FLIPKART")) == "National"
    # all-dormant sheet (only '0' in the channel column) -> can't tell, fall back to path
    assert _sub_platform_from_channel(_channel_col("0")) is None


def test_campaign_type_folds_to_pla_pca():
    # the flipkart_campaign signature maps Campaign Type -> ad_type; normalize must
    # fold the full names to PLA/PCA.
    cols = ["Campaign ID", "Name", "Campaign Type", "campaign_status",
            "Campaign Allocated Budget", "Ad Spends", "Views", "Clicks",
            "Total Units Sold", "Total Revenue", "ROI", "CTR"]
    sig = detect(cols)
    assert sig and sig.key == "flipkart_campaign"
    df = pd.DataFrame([
        ["C1", "FM-PCA-Filter", "Product Contextual Ads", "Live", 1500, 182, 3643, 13, 2, 263, 1.44, 0.0035],
        ["C2", "FM-PLA-Instant", "Product Listing Ads", "Live", 2000, 500, 9000, 40, 6, 900, 1.8, 0.004],
    ], columns=cols)
    ds = Dataset(path=None, sha256="x", sheet_name="", signature=sig, df=df,
                 sub_platform="Minutes")
    out = normalize(ds)
    assert set(out["ad_type"]) == {"PCA", "PLA"}, list(out["ad_type"])


if __name__ == "__main__":
    test_channel_to_sub_platform()
    test_campaign_type_folds_to_pla_pca()
    print("ok")
