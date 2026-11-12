"""Company selection and SEC 10-K filing management orchestration for FinovaLabs."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

from pydantic import BaseModel

from finova_labs.exceptions import FinovaError
from finova_labs.logging_config import get_logger
from finova_labs.sec_client import SecEdgarClient

logger = get_logger("filing_manager")


class SupportedCompany(BaseModel):
    """Supported company option (resolved dynamically to CIK via SEC EDGAR)."""

    label: str
    ticker: str

    @property
    def display_name(self) -> str:
        return f"{self.label} ({self.ticker})"


SUPPORTED_COMPANIES: tuple[SupportedCompany, ...] = (
    SupportedCompany(label="Apple", ticker="AAPL"),
    SupportedCompany(label="Microsoft", ticker="MSFT"),
    SupportedCompany(label="Alphabet", ticker="GOOGL"),
    SupportedCompany(label="Amazon", ticker="AMZN"),
    SupportedCompany(label="Walmart", ticker="WMT"),
)

_TICKER_LABELS: dict[str, str] = {c.ticker: c.label for c in SUPPORTED_COMPANIES}


class CompanyRetrievalOutcome(BaseModel):
    """Result of retrieving the latest 10-K filing for one selected company."""

    ticker: str
    company_name: str
    cik: str | None = None
    filing_type: str = "10-K"
    filing_date: str | None = None
    fiscal_year: int | None = None
    accession_number: str | None = None
    filing_url: str | None = None
    retrieval_status: str = "FAILED"
    from_cache: bool = False
    error_message: str | None = None
    error_hint: str | None = None


def get_supported_company_options() -> tuple[SupportedCompany, ...]:
    """Return the configured list of supported FinovaLabs companies."""
    return SUPPORTED_COMPANIES


def retrieve_company_10k(
    ticker: str,
    client: SecEdgarClient,
    force_refresh: bool = False,
    db_path: Path | str | None = None,
) -> CompanyRetrievalOutcome:
    """Resolve real SEC CIK, retrieve latest 10-K + Company Facts, and persist metadata.

    Never returns ``RETRIEVED`` unless the SEC EDGAR requests succeed.
    """
    cleaned_ticker = ticker.strip().upper()
    fallback_name = _TICKER_LABELS.get(cleaned_ticker, cleaned_ticker)

    try:
        bundle = client.fetch_latest_10k_bundle(
            ticker=cleaned_ticker,
            persist=True,
            force_refresh=force_refresh,
            db_path=db_path,
        )
    except FinovaError as exc:
        logger.warning("Filing retrieval failed for %s: %s", cleaned_ticker, exc)
        return CompanyRetrievalOutcome(
            ticker=cleaned_ticker,
            company_name=fallback_name,
            retrieval_status="FAILED",
            error_message=exc.message,
            error_hint=exc.hint,
        )
    except Exception as exc:  # pragma: no cover - defensive boundary
        logger.exception("Unexpected retrieval failure for %s", cleaned_ticker)
        return CompanyRetrievalOutcome(
            ticker=cleaned_ticker,
            company_name=fallback_name,
            retrieval_status="FAILED",
            error_message=str(exc),
            error_hint="Inspect data/logs/finova_labs.log for diagnostic details.",
        )

    filing = bundle.latest_10k
    return CompanyRetrievalOutcome(
        ticker=bundle.company.ticker,
        company_name=filing.company_name or bundle.company.company_name,
        cik=bundle.company.cik,
        filing_type=filing.form_type,
        filing_date=filing.filing_date,
        fiscal_year=filing.fiscal_year,
        accession_number=filing.accession_number,
        filing_url=filing.filing_url,
        retrieval_status="RETRIEVED",
        from_cache=bundle.company.from_cache and bundle.company_facts.from_cache,
    )


def retrieve_selected_companies(
    tickers: Sequence[str],
    force_refresh: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
    client: SecEdgarClient | None = None,
    db_path: Path | str | None = None,
) -> list[CompanyRetrievalOutcome]:
    """Retrieve latest 10-K filings for one or more selected company tickers."""
    cleaned_tickers = [t.strip().upper() for t in tickers if t and t.strip()]
    if not cleaned_tickers:
        return []

    try:
        sec_client = client or SecEdgarClient()
    except FinovaError as exc:
        logger.warning("Unable to initialize SEC client: %s", exc)
        return [
            CompanyRetrievalOutcome(
                ticker=t,
                company_name=_TICKER_LABELS.get(t, t),
                retrieval_status="FAILED",
                error_message=exc.message,
                error_hint=exc.hint,
            )
            for t in cleaned_tickers
        ]

    outcomes: list[CompanyRetrievalOutcome] = []
    total = len(cleaned_tickers)
    for index, ticker in enumerate(cleaned_tickers, start=1):
        if on_progress is not None:
            on_progress(index, total, ticker)
        outcomes.append(
            retrieve_company_10k(
                ticker=ticker,
                client=sec_client,
                force_refresh=force_refresh,
                db_path=db_path,
            )
        )
    return outcomes

