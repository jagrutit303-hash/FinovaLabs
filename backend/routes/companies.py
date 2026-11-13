"""Companies and SEC Form 10-K filings routes."""

from __future__ import annotations

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.auth import AuthUser, require_role
from backend.dependencies import DbPathDep, SettingsDep
from backend.schemas import CompanyResponse, FilingResponse
from finova_labs.database import fetch_filing_metadata
from finova_labs.filing_manager import (
    get_supported_company_options,
    retrieve_selected_companies,
)
from finova_labs.sec_client import SecEdgarClient, normalize_cik

router = APIRouter(tags=["Companies & Filings"])


class CompanyRetrieveRequest(BaseModel):
    tickers: list[str] = Field(min_length=1, description="List of company tickers to retrieve")
    force_refresh: bool = False


KNOWN_CIKS: dict[str, str] = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "GOOGL": "0001652044",
    "AMZN": "0001018724",
    "WMT": "0000104169",
}


@router.get("/api/companies", response_model=list[CompanyResponse])
def get_companies(
    q: str | None = Query(default=None, description="Search filter for ticker or company name"),
    settings: SettingsDep = None,
) -> list[CompanyResponse]:
    """List or search US equities dynamically resolved via SEC EDGAR company_tickers cache."""
    options = get_supported_company_options()
    supported_results = [
        CompanyResponse(
            company_id=c.ticker,
            ticker=c.ticker,
            cik=KNOWN_CIKS.get(c.ticker),
            company_name=c.label,
            display_name=c.display_name,
        )
        for c in options
    ]

    if not q or not q.strip():
        return supported_results

    term = q.strip().upper()
    # Check if matches any supported company first
    matched_supported = [
        c for c in supported_results
        if term in c.ticker.upper() or term in c.company_name.upper()
    ]

    # Search company_tickers.json cache for additional or exact matches
    extra_matches: list[CompanyResponse] = []
    try:
        import json
        from pathlib import Path
        cache_file = Path(settings.sec.cache_dir if settings else "data/cache/sec") / "company_tickers.json"
        if cache_file.is_file():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            for item in data.values():
                if not isinstance(item, dict):
                    continue
                tick = str(item.get("ticker", "")).strip().upper()
                title = str(item.get("title", "")).strip()
                if term == tick or term in tick or term in title.upper():
                    if any(s.ticker == tick for s in matched_supported):
                        continue
                    cik_val = normalize_cik(item.get("cik_str", 0))
                    extra_matches.append(
                        CompanyResponse(
                            company_id=tick,
                            ticker=tick,
                            cik=cik_val,
                            company_name=title,
                            display_name=f"{title} ({tick})",
                        )
                    )
                    if len(extra_matches) >= 8:
                        break
    except Exception:
        pass

    return matched_supported + extra_matches


@router.get("/api/companies/{company_id}/filings", response_model=list[FilingResponse])
def get_company_filings(
    company_id: str,
    db_path: DbPathDep,
    settings: SettingsDep,
    auto_retrieve: bool = Query(default=True, description="Retrieve latest 10-K from SEC if missing"),
) -> list[FilingResponse]:
    """Fetch stored SEC 10-K filings for a company by ticker or CIK."""
    resolved_cik = None
    target_ticker = None
    options = get_supported_company_options()

    clean_id = company_id.strip().upper()
    for opt in options:
        opt_cik = KNOWN_CIKS.get(opt.ticker.upper())
        if opt.ticker.upper() == clean_id or (opt_cik and (opt_cik == clean_id or opt_cik == clean_id.zfill(10))):
            resolved_cik = opt_cik
            target_ticker = opt.ticker
            break

    if not resolved_cik:
        try:
            resolved_cik = normalize_cik(company_id)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Company identifier '{company_id}' is not supported. Use one of AAPL, MSFT, GOOGL, AMZN, WMT.",
            )

    filings = fetch_filing_metadata(cik=resolved_cik, db_path=db_path)

    # If no local records exist and auto_retrieve is enabled, fetch from SEC EDGAR
    if not filings and auto_retrieve and target_ticker:
        client = SecEdgarClient(settings=settings)
        try:
            bundle = client.fetch_latest_10k_bundle(target_ticker, persist=True, db_path=db_path)
            if bundle and bundle.latest_10k:
                filings = fetch_filing_metadata(cik=resolved_cik, db_path=db_path)
        except Exception as exc:
            # If SEC retrieval fails, continue returning empty list or cached data
            pass

    return [
        FilingResponse(
            id=f.get("id"),
            cik=f["cik"],
            ticker=f.get("ticker") or target_ticker,
            company_name=f.get("company_name"),
            accession_number=f["accession_number"],
            form_type=f["form_type"],
            filing_date=f["filing_date"],
            reporting_period=f.get("reporting_period"),
            fiscal_year=f.get("fiscal_year"),
            retrieval_status=f.get("retrieval_status", "RETRIEVED"),
            filing_url=f.get("filing_url"),
            fetched_at=f.get("fetched_at"),
        )
        for f in filings
    ]


@router.post("/api/filings/retrieve", response_model=list[FilingResponse])
def retrieve_filings(
    payload: CompanyRetrieveRequest,
    db_path: DbPathDep,
    user: Annotated[AuthUser, Depends(require_role(["analyst", "admin"]))],
) -> list[FilingResponse]:
    """Trigger official SEC EDGAR 10-K retrieval for selected companies."""
    outcomes = retrieve_selected_companies(
        tickers=payload.tickers,
        force_refresh=payload.force_refresh,
        db_path=db_path,
    )
    succeeded_ciks = [o.cik for o in outcomes if o.cik]
    all_filings = []
    for cik in succeeded_ciks:
        meta = fetch_filing_metadata(cik=cik, db_path=db_path)
        all_filings.extend(meta)

    return [
        FilingResponse(
            id=f.get("id"),
            cik=f["cik"],
            ticker=f.get("ticker"),
            company_name=f.get("company_name"),
            accession_number=f["accession_number"],
            form_type=f["form_type"],
            filing_date=f["filing_date"],
            reporting_period=f.get("reporting_period"),
            fiscal_year=f.get("fiscal_year"),
            retrieval_status=f.get("retrieval_status", "RETRIEVED"),
            filing_url=f.get("filing_url"),
            fetched_at=f.get("fetched_at"),
        )
        for f in all_filings
    ]

