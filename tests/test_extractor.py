"""Offline unit tests for 8-metric extraction, HTML evidence, ambiguity, and SQLite."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from finova_labs.database import fetch_extracted_metrics, init_db
from finova_labs.extractor import extract_metrics_for_filing
from finova_labs.filing_parser import parse_filing_html
from finova_labs.sec_client import FilingMetadata


def _sample_filing() -> FilingMetadata:
    return FilingMetadata(
        cik="0000320193",
        ticker="TEST",
        company_name="Test Corp",
        accession_number="0000320193-26-000001",
        form_type="10-K",
        filing_date="2026-11-01",
        reporting_period="2026-09-26",
        fiscal_year=2026,
        primary_document="test-20260926.htm",
        filing_url="https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/test-20260926.htm",
        submissions_url="https://data.sec.gov/submissions/CIK0000320193.json",
        companyfacts_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
    )


def _sample_html() -> str:
    return """
    <html><body>
      <ix:header>
        <ix:resources>
          <xbrli:context id="c_fy">
            <xbrli:period><xbrli:startDate>2025-09-28</xbrli:startDate><xbrli:endDate>2026-09-26</xbrli:endDate></xbrli:period>
          </xbrli:context>
          <xbrli:context id="c_seg">
            <xbrli:entity><xbrli:segment><xbrldi:explicitMember dimension="srt:ProductOrServiceAxis">x:Phone</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
            <xbrli:period><xbrli:startDate>2025-09-28</xbrli:startDate><xbrli:endDate>2026-09-26</xbrli:endDate></xbrli:period>
          </xbrli:context>
          <xbrli:context id="c_inst">
            <xbrli:period><xbrli:instant>2026-09-26</xbrli:instant></xbrli:period>
          </xbrli:context>
          <xbrli:unit id="u_usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
          <xbrli:unit id="u_eps"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>
        </ix:resources>
      </ix:header>
      <table>
        <tr><td>Total net sales</td><td><ix:nonFraction name="us-gaap:Revenues" contextRef="c_fy" unitRef="u_usd" scale="6">120,000</ix:nonFraction></td></tr>
        <tr><td>Phone segment sales</td><td><ix:nonFraction name="us-gaap:Revenues" contextRef="c_seg" unitRef="u_usd" scale="6">60,000</ix:nonFraction></td></tr>
        <tr><td>Net loss</td><td>(<ix:nonFraction name="us-gaap:NetIncomeLoss" contextRef="c_fy" unitRef="u_usd" scale="6" sign="-">2,500</ix:nonFraction>)</td></tr>
        <tr><td>Diluted EPS</td><td>(<ix:nonFraction name="us-gaap:EarningsPerShareDiluted" contextRef="c_fy" unitRef="u_eps" scale="0" sign="-">1.25</ix:nonFraction>)</td></tr>
      </table>
    </body></html>
    """


def test_parse_filing_html_excludes_dimensions_and_handles_negatives() -> None:
    """HTML parser extracts scaled Decimal facts, signs, and skips dimensional rows when filtered."""
    parsed = parse_filing_html(_sample_html())
    rev_facts = parsed.facts_by_concept["Revenues"]
    assert len(rev_facts) == 2
    consolidated = [f for f in rev_facts if not f.has_dimensions]
    assert len(consolidated) == 1
    assert consolidated[0].normalized_value == Decimal("120000000000")
    assert consolidated[0].scale_factor == 1_000_000
    assert "Table #1, Row #1" in consolidated[0].evidence_location

    ni = parsed.facts_by_concept["NetIncomeLoss"][0]
    assert ni.normalized_value == Decimal("-2500000000")


def test_extractor_handles_annual_filtering_ambiguity_missing_and_sqlite(tmp_path: Path) -> None:
    """Extractor separates annual vs quarterly, flags ambiguity, leaves missing blank, and persists."""
    db_file = tmp_path / "extract.db"
    init_db(db_file)
    filing = _sample_filing()
    acc = filing.accession_number

    company_facts = {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        # Quarterly value should be ignored!
                        {"accn": acc, "form": "10-K", "start": "2026-06-28", "end": "2026-09-26", "val": 30000000000, "fp": "FY"},
                        # Annual value should win and link to HTML evidence
                        {"accn": acc, "form": "10-K", "start": "2025-09-28", "end": "2026-09-26", "val": 120000000000, "fp": "FY"},
                    ]
                }
            },
            "NetIncomeLoss": {
                "units": {
                    "USD": [
                        {"accn": acc, "form": "10-K", "start": "2025-09-28", "end": "2026-09-26", "val": -2500000000, "fp": "FY"}
                    ]
                }
            },
            # Ambiguous Total Assets (two conflicting values for exact same accession + instant!)
            "Assets": {
                "units": {
                    "USD": [
                        {"accn": acc, "form": "10-K", "end": "2026-09-26", "val": 500000000000, "fp": "FY"},
                        {"accn": acc, "form": "10-K", "end": "2026-09-26", "val": 510000000000, "fp": "FY"},
                    ]
                }
            },
            "EarningsPerShareDiluted": {
                "units": {
                    "USD/shares": [
                        {"accn": acc, "form": "10-K", "start": "2025-09-28", "end": "2026-09-26", "val": -1.25, "fp": "FY"}
                    ]
                }
            },
        }
    }

    records = extract_metrics_for_filing(
        filing=filing,
        company_facts=company_facts,
        html_text=_sample_html(),
        persist=True,
        db_path=db_file,
    )
    by_name = {r.metric_name: r for r in records}
    assert len(by_name) == 8

    # Revenue extracted from annual period + enriched with HTML evidence & scale
    rev = by_name["Revenue"]
    assert rev.extraction_status == "EXTRACTED"
    assert rev.normalized_value == Decimal("120000000000")
    assert rev.raw_value == "120,000"
    assert rev.scale_factor == 1_000_000
    assert "Table #1, Row #1" in rev.evidence_location

    # Negative Net Income & EPS
    assert by_name["Net Income"].normalized_value == Decimal("-2500000000")
    assert by_name["Earnings Per Share"].normalized_value == Decimal("-1.25")
    assert by_name["Earnings Per Share"].reported_unit == "USD/shares"

    # Ambiguous Total Assets must NOT silently pick a number
    assets = by_name["Total Assets"]
    assert assets.extraction_status == "AMBIGUOUS"
    assert assets.normalized_value is None
    assert assets.review_status == "REVIEW_REQUIRED"
    assert len(assets.candidates) == 2

    # Missing metrics must NEVER be fabricated
    liab = by_name["Total Liabilities"]
    assert liab.extraction_status == "MISSING"
    assert liab.normalized_value is None

    # Verify SQLite persistence
    rows = fetch_extracted_metrics(accession_number=acc, db_path=db_file)
    assert len(rows) == 8
    stored_rev = next(r for r in rows if r["metric_name"] == "Revenue")
    assert stored_rev["normalized_decimal"] == "120000000000"
    assert stored_rev["scale_factor"] == 1_000_000

