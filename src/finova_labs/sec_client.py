"""SEC EDGAR client for ticker lookup, submissions, 10-K metadata, and Company Facts."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests
from pydantic import BaseModel, Field

from finova_labs.audit import record_audit_event
from finova_labs.database import init_db, save_filing_metadata
from finova_labs.exceptions import SecClientError
from finova_labs.logging_config import get_logger
from finova_labs.settings import Settings, get_settings, resolve_sec_user_agent

logger = get_logger("sec_client")

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL_TEMPLATE = "https://data.sec.gov/submissions/CIK{cik}.json"
SUBMISSIONS_ARCHIVE_URL_TEMPLATE = "https://data.sec.gov/submissions/{filename}"
COMPANY_FACTS_URL_TEMPLATE = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
ARCHIVES_DOC_URL_TEMPLATE = (
    "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{primary_doc}"
)

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class CompanyInfo(BaseModel):
    """Resolved SEC entity metadata from company_tickers.json."""

    ticker: str
    cik: str
    company_name: str
    source_url: str = COMPANY_TICKERS_URL
    from_cache: bool = False


class FilingMetadata(BaseModel):
    """Normalized SEC filing metadata with official source URLs."""

    cik: str
    ticker: str | None = None
    company_name: str | None = None
    accession_number: str
    form_type: str
    filing_date: str
    reporting_period: str | None = None
    fiscal_year: int | None = None
    retrieval_status: str = "RETRIEVED"
    primary_document: str | None = None
    primary_doc_description: str | None = None
    filing_url: str
    submissions_url: str
    companyfacts_url: str
    fetched_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class CompanyFactsResult(BaseModel):
    """SEC Company Facts JSON wrapper with provenance metadata."""

    cik: str
    entity_name: str | None = None
    source_url: str
    from_cache: bool = False
    cache_path: str
    facts: dict[str, Any]


class SecFilingBundle(BaseModel):
    """Combined result of company lookup, latest 10-K metadata, and Company Facts."""

    company: CompanyInfo
    latest_10k: FilingMetadata
    company_facts: CompanyFactsResult
    db_filing_id: int | None = None


def normalize_cik(cik: str | int) -> str:
    """Validate and zero-pad a numeric SEC CIK to 10 characters."""
    raw = str(cik).strip()
    if raw.upper().startswith("CIK"):
        raw = raw[3:]
    if not raw or not raw.isdigit():
        raise SecClientError(
            f"Invalid SEC CIK '{cik}'.",
            hint="CIK must contain only digits (for example '0000320193' or '320193').",
        )
    if len(raw) > 10:
        raise SecClientError(f"SEC CIK '{cik}' exceeds 10 digits.")
    return raw.zfill(10)


def build_filing_document_url(
    cik: str,
    accession_number: str,
    primary_document: str | None,
) -> str:
    """Build the official SEC Archives URL for a filing or its submission directory."""
    cik_int = int(normalize_cik(cik))
    acc_nodash = accession_number.replace("-", "").strip()
    if primary_document and primary_document.strip():
        return ARCHIVES_DOC_URL_TEMPLATE.format(
            cik_int=cik_int,
            accession_nodash=acc_nodash,
            primary_doc=primary_document.strip().lstrip("/"),
        )
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/"


def infer_fiscal_year(
    accession_number: str,
    reporting_period: str | None,
    filing_date: str,
    facts: dict[str, Any] | None = None,
) -> int | None:
    """Determine fiscal year from SEC Company Facts (matching accession) or report period."""
    if isinstance(facts, dict):
        us_gaap = facts.get("us-gaap")
        if isinstance(us_gaap, dict):
            fy_counts: dict[int, int] = {}
            for concept_data in us_gaap.values():
                units = concept_data.get("units") if isinstance(concept_data, dict) else None
                if not isinstance(units, dict):
                    continue
                for items in units.values():
                    if not isinstance(items, list):
                        continue
                    for entry in items:
                        if not isinstance(entry, dict):
                            continue
                        if (
                            entry.get("accn") == accession_number
                            and entry.get("form") == "10-K"
                            and isinstance(entry.get("fy"), int)
                        ):
                            fy_val = int(entry["fy"])
                            fy_counts[fy_val] = fy_counts.get(fy_val, 0) + 1
            if fy_counts:
                return max(fy_counts, key=lambda yr: fy_counts[yr])

    for date_str in (reporting_period, filing_date):
        if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
            return int(date_str[:4])
    return None


class SecEdgarClient:
    """Rate-limited, cached HTTP client for official SEC EDGAR JSON endpoints."""

    def __init__(
        self,
        settings: Settings | None = None,
        user_agent: str | None = None,
        session: requests.Session | None = None,
        max_retries: int = 3,
        backoff_seconds: float = 0.75,
        ticker_cache_ttl_seconds: int = 86_400,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or get_settings()
        self.user_agent = user_agent or resolve_sec_user_agent(
            self.settings, require_real_email=True
        )
        self.cache_dir: Path = self.settings.cache_path
        self.timeout_seconds: int = self.settings.sec.request_timeout_seconds
        self.min_request_interval: float = 1.0 / max(
            self.settings.sec.max_requests_per_second, 1
        )
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.ticker_cache_ttl_seconds = ticker_cache_ttl_seconds
        self._sleep = sleep_fn
        self._monotonic = monotonic_fn
        self._last_request_at: float | None = None

        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
            }
        )

    def _respect_rate_limit(self) -> None:
        """Sleep if needed to stay under the configured SEC requests/sec ceiling."""
        if self._last_request_at is not None:
            elapsed = self._monotonic() - self._last_request_at
            remaining = self.min_request_interval - elapsed
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._monotonic()

    def _read_cache(
        self,
        cache_file: Path,
        max_age_seconds: int | None = None,
    ) -> Any | None:
        """Read cached JSON from disk if present and unexpired."""
        if not cache_file.is_file():
            return None
        if max_age_seconds is not None:
            age = time.time() - cache_file.stat().st_mtime
            if age > max_age_seconds:
                return None
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring unreadable SEC cache file %s: %s", cache_file, exc)
            return None

    def _write_cache(self, cache_file: Path, payload: Any) -> None:
        """Persist JSON response safely under data/cache/sec/."""
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Unable to write SEC cache file %s: %s", cache_file, exc)

    def _request_response(
        self,
        url: str,
        accept: str = "application/json",
    ) -> requests.Response:
        """Perform a rate-limited, retry-safe GET request returning HTTP 200 Response."""
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self._respect_rate_limit()
            try:
                response = self.session.get(
                    url,
                    headers={"Accept": accept},
                    timeout=self.timeout_seconds,
                )
            except requests.Timeout as exc:
                last_error = exc
                logger.warning("SEC request timed out (%s), attempt %s", url, attempt + 1)
                if attempt < self.max_retries:
                    self._sleep(self.backoff_seconds * (2**attempt))
                    continue
                raise SecClientError(
                    f"Request to SEC EDGAR timed out after {self.max_retries + 1} attempts: {url}",
                    hint="Check your internet connection or increase request_timeout_seconds in config.yaml.",
                ) from exc
            except requests.RequestException as exc:
                last_error = exc
                logger.warning("SEC network error (%s): %s", url, exc)
                if attempt < self.max_retries:
                    self._sleep(self.backoff_seconds * (2**attempt))
                    continue
                raise SecClientError(
                    f"Network error contacting SEC EDGAR ({url}): {exc}",
                    hint="Verify network connectivity and DNS access to sec.gov.",
                ) from exc

            status = response.status_code
            if status == 200:
                return response

            if status == 403:
                raise SecClientError(
                    f"SEC EDGAR rejected the request with HTTP 403 for {url}",
                    hint="Ensure FINOVALABS_SEC_CONTACT_EMAIL in .env is set to a legitimate email address.",
                )

            if status == 404:
                raise SecClientError(
                    f"SEC EDGAR resource not found (HTTP 404): {url}",
                    hint="Confirm the company CIK has filings or Company Facts published.",
                )

            if status in _RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                retry_after = response.headers.get("Retry-After", "").strip()
                delay = (
                    float(retry_after)
                    if retry_after.isdigit()
                    else self.backoff_seconds * (2**attempt)
                )
                logger.warning(
                    "SEC HTTP %s for %s; retrying in %.2fs", status, url, delay
                )
                self._sleep(delay)
                continue

            raise SecClientError(
                f"SEC EDGAR returned unexpected HTTP {status} for {url}",
                hint="Try again shortly; SEC servers may be temporarily rate-limiting or unavailable.",
            )

        raise SecClientError(f"SEC EDGAR request failed for {url}: {last_error}")

    def _request_json(self, url: str) -> Any:
        """Perform a rate-limited, retry-safe GET request returning parsed JSON."""
        response = self._request_response(url, accept="application/json")
        try:
            return response.json()
        except ValueError as exc:
            raise SecClientError(
                f"Malformed JSON returned by SEC EDGAR for {url}",
                hint="Retry with force_refresh=True or inspect the SEC endpoint response.",
            ) from exc

    def _fetch_cached_json(
        self,
        url: str,
        cache_file: Path,
        force_refresh: bool = False,
        max_age_seconds: int | None = None,
    ) -> tuple[Any, bool]:
        """Return ``(parsed_json, from_cache)`` using local disk cache when valid."""
        if not force_refresh:
            cached = self._read_cache(cache_file, max_age_seconds=max_age_seconds)
            if cached is not None:
                logger.info("SEC cache hit: %s", cache_file)
                return cached, True

        logger.info("Fetching SEC endpoint: %s", url)
        data = self._request_json(url)
        self._write_cache(cache_file, data)
        return data, False

    def lookup_company_by_ticker(
        self,
        ticker: str,
        force_refresh: bool = False,
    ) -> CompanyInfo:
        """Resolve a stock ticker symbol to its 10-digit CIK and entity name."""
        cleaned = ticker.strip().upper()
        if not cleaned:
            raise SecClientError(
                "Ticker symbol cannot be empty.",
                hint="Provide a valid US stock ticker such as AAPL or MSFT.",
            )

        cache_file = self.cache_dir / "company_tickers.json"
        payload, from_cache = self._fetch_cached_json(
            COMPANY_TICKERS_URL,
            cache_file=cache_file,
            force_refresh=force_refresh,
            max_age_seconds=self.ticker_cache_ttl_seconds,
        )

        if not isinstance(payload, dict) or not payload:
            raise SecClientError(
                "SEC company_tickers.json response has an unexpected format.",
                hint="Delete the cached company_tickers.json file and retry.",
            )

        candidates = {cleaned, cleaned.replace(".", "-"), cleaned.replace("-", ".")}
        for entry in payload.values():
            if not isinstance(entry, dict):
                continue
            entry_ticker = str(entry.get("ticker", "")).strip().upper()
            if entry_ticker in candidates:
                cik = normalize_cik(entry.get("cik_str", ""))
                title = str(entry.get("title", "")).strip() or entry_ticker
                return CompanyInfo(
                    ticker=entry_ticker,
                    cik=cik,
                    company_name=title,
                    source_url=COMPANY_TICKERS_URL,
                    from_cache=from_cache,
                )

        raise SecClientError(
            f"Ticker '{cleaned}' was not found in SEC company_tickers.json.",
            hint="Verify the ticker symbol on SEC EDGAR (for example AAPL, MSFT, NVDA).",
        )

    def get_submissions(
        self,
        cik: str | int,
        force_refresh: bool = False,
    ) -> tuple[dict[str, Any], bool, Path]:
        """Fetch and validate the SEC submissions JSON for a 10-digit CIK."""
        cik10 = normalize_cik(cik)
        url = SUBMISSIONS_URL_TEMPLATE.format(cik=cik10)
        cache_file = self.cache_dir / "submissions" / f"CIK{cik10}.json"
        payload, from_cache = self._fetch_cached_json(
            url,
            cache_file=cache_file,
            force_refresh=force_refresh,
        )

        if not isinstance(payload, dict) or "filings" not in payload:
            raise SecClientError(
                f"Malformed SEC submissions response for CIK {cik10}.",
                hint="Expected JSON object containing a 'filings' key.",
            )
        return payload, from_cache, cache_file

    def _parse_recent_block(
        self,
        block: dict[str, Any],
        cik10: str,
        ticker: str | None,
        company_name: str | None,
        submissions_url: str,
        companyfacts_url: str,
    ) -> list[FilingMetadata]:
        """Parse a columnar SEC submissions block into FilingMetadata records."""
        forms = block.get("form")
        accessions = block.get("accessionNumber")
        filing_dates = block.get("filingDate")
        report_dates = block.get("reportDate") or []
        primary_docs = block.get("primaryDocument") or []
        descriptions = block.get("primaryDocDescription") or []

        if not (
            isinstance(forms, list)
            and isinstance(accessions, list)
            and isinstance(filing_dates, list)
        ):
            raise SecClientError(
                f"Malformed filing arrays in SEC submissions for CIK {cik10}."
            )

        count = min(len(forms), len(accessions), len(filing_dates))
        records: list[FilingMetadata] = []
        for idx in range(count):
            acc_no = str(accessions[idx]).strip()
            form = str(forms[idx]).strip()
            f_date = str(filing_dates[idx]).strip()
            if not (acc_no and form and f_date):
                continue

            rep_period = (
                str(report_dates[idx]).strip() or None
                if idx < len(report_dates) and report_dates[idx]
                else None
            )
            primary_doc = (
                str(primary_docs[idx]).strip() or None
                if idx < len(primary_docs) and primary_docs[idx]
                else None
            )
            doc_desc = (
                str(descriptions[idx]).strip() or None
                if idx < len(descriptions) and descriptions[idx]
                else None
            )

            records.append(
                FilingMetadata(
                    cik=cik10,
                    ticker=ticker,
                    company_name=company_name,
                    accession_number=acc_no,
                    form_type=form,
                    filing_date=f_date,
                    reporting_period=rep_period,
                    primary_document=primary_doc,
                    primary_doc_description=doc_desc,
                    filing_url=build_filing_document_url(cik10, acc_no, primary_doc),
                    submissions_url=submissions_url,
                    companyfacts_url=companyfacts_url,
                )
            )
        return records

    def get_filing_history(
        self,
        cik: str | int,
        form_types: tuple[str, ...] | None = None,
        limit: int = 50,
        ticker: str | None = None,
        force_refresh: bool = False,
    ) -> list[FilingMetadata]:
        """Retrieve filing history for a CIK, optionally filtered by form type."""
        cik10 = normalize_cik(cik)
        submissions, _, _ = self.get_submissions(cik10, force_refresh=force_refresh)

        filings_root = submissions.get("filings")
        if not isinstance(filings_root, dict) or not isinstance(
            filings_root.get("recent"), dict
        ):
            raise SecClientError(
                f"SEC submissions JSON for CIK {cik10} is missing 'filings.recent'."
            )

        tickers_list = submissions.get("tickers") or []
        resolved_ticker = ticker or (
            str(tickers_list[0]).strip().upper() if tickers_list else None
        )
        company_name = str(submissions.get("name", "")).strip() or None
        submissions_url = SUBMISSIONS_URL_TEMPLATE.format(cik=cik10)
        companyfacts_url = COMPANY_FACTS_URL_TEMPLATE.format(cik=cik10)

        allowed = {f.upper() for f in form_types} if form_types else None
        records = self._parse_recent_block(
            block=filings_root["recent"],
            cik10=cik10,
            ticker=resolved_ticker,
            company_name=company_name,
            submissions_url=submissions_url,
            companyfacts_url=companyfacts_url,
        )
        if allowed:
            records = [r for r in records if r.form_type.upper() in allowed]

        # Fall back to older submission archive files if recent filings have no match.
        if not records and allowed:
            archive_files = filings_root.get("files") or []
            for file_meta in archive_files:
                if not isinstance(file_meta, dict) or not file_meta.get("name"):
                    continue
                fname = str(file_meta["name"]).strip()
                arch_url = SUBMISSIONS_ARCHIVE_URL_TEMPLATE.format(filename=fname)
                arch_cache = self.cache_dir / "submissions" / fname
                arch_payload, _ = self._fetch_cached_json(
                    arch_url,
                    cache_file=arch_cache,
                    force_refresh=force_refresh,
                )
                if isinstance(arch_payload, dict):
                    more = self._parse_recent_block(
                        block=arch_payload,
                        cik10=cik10,
                        ticker=resolved_ticker,
                        company_name=company_name,
                        submissions_url=submissions_url,
                        companyfacts_url=companyfacts_url,
                    )
                    records.extend(r for r in more if r.form_type.upper() in allowed)
                    if records:
                        break

        records.sort(key=lambda r: r.filing_date, reverse=True)
        return records[:limit]

    def get_latest_10k(
        self,
        cik: str | int,
        ticker: str | None = None,
        include_amendments: bool = False,
        force_refresh: bool = False,
    ) -> FilingMetadata:
        """Locate the most recent Form 10-K filing metadata for a CIK."""
        cik10 = normalize_cik(cik)
        forms = ("10-K", "10-K/A") if include_amendments else ("10-K",)
        filings = self.get_filing_history(
            cik=cik10,
            form_types=forms,
            limit=10,
            ticker=ticker,
            force_refresh=force_refresh,
        )
        if not filings:
            raise SecClientError(
                f"No Form 10-K filings found for CIK {cik10}.",
                hint="This entity may be a foreign private issuer (20-F/40-F) or have no annual 10-K history.",
            )
        return filings[0]

    def get_company_facts(
        self,
        cik: str | int,
        force_refresh: bool = False,
    ) -> CompanyFactsResult:
        """Retrieve and cache SEC XBRL Company Facts JSON for a CIK."""
        cik10 = normalize_cik(cik)
        url = COMPANY_FACTS_URL_TEMPLATE.format(cik=cik10)
        cache_file = self.cache_dir / "companyfacts" / f"CIK{cik10}.json"
        payload, from_cache = self._fetch_cached_json(
            url,
            cache_file=cache_file,
            force_refresh=force_refresh,
        )

        if not isinstance(payload, dict) or not isinstance(payload.get("facts"), dict):
            raise SecClientError(
                f"Malformed SEC Company Facts response for CIK {cik10}.",
                hint="Expected JSON object containing a 'facts' dictionary.",
            )

        return CompanyFactsResult(
            cik=cik10,
            entity_name=str(payload.get("entityName", "")).strip() or None,
            source_url=url,
            from_cache=from_cache,
            cache_path=str(cache_file),
            facts=payload["facts"],
        )

    def get_filing_html(
        self,
        filing_url: str,
        cik: str | int,
        accession_number: str,
        primary_document: str | None = None,
        force_refresh: bool = False,
    ) -> tuple[str, bool, Path]:
        """Download and locally cache the primary 10-K HTML document."""
        cik10 = normalize_cik(cik)
        acc_nodash = accession_number.replace("-", "").strip()
        doc_name = (primary_document or f"{acc_nodash}.htm").strip().lstrip("/")
        safe_name = doc_name.replace("/", "_")
        cache_file = self.cache_dir / "filings" / f"CIK{cik10}_{acc_nodash}_{safe_name}"

        if not force_refresh and cache_file.is_file():
            try:
                text = cache_file.read_text(encoding="utf-8", errors="replace")
                if text.strip():
                    logger.info("SEC HTML cache hit: %s", cache_file)
                    return text, True, cache_file
            except OSError as exc:
                logger.warning("Ignoring unreadable cached HTML %s: %s", cache_file, exc)

        logger.info("Fetching SEC filing HTML: %s", filing_url)
        response = self._request_response(
            filing_url,
            accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        )
        html_text = response.text
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(html_text, encoding="utf-8")
        except OSError as exc:
            logger.warning("Unable to cache SEC filing HTML %s: %s", cache_file, exc)
        return html_text, False, cache_file

    def fetch_latest_10k_bundle(
        self,
        ticker: str,
        persist: bool = True,
        force_refresh: bool = False,
        db_path: Path | str | None = None,
    ) -> SecFilingBundle:
        """Resolve ticker -> CIK -> latest 10-K metadata -> Company Facts, and persist."""
        company = self.lookup_company_by_ticker(ticker, force_refresh=force_refresh)
        latest_10k = self.get_latest_10k(
            cik=company.cik,
            ticker=company.ticker,
            force_refresh=force_refresh,
        )
        if not latest_10k.company_name:
            latest_10k.company_name = company.company_name
        company_facts = self.get_company_facts(
            cik=company.cik,
            force_refresh=force_refresh,
        )
        latest_10k.fiscal_year = infer_fiscal_year(
            accession_number=latest_10k.accession_number,
            reporting_period=latest_10k.reporting_period,
            filing_date=latest_10k.filing_date,
            facts=company_facts.facts,
        )
        latest_10k.retrieval_status = "RETRIEVED"

        db_id: int | None = None
        if persist:
            init_db(db_path)
            db_id = save_filing_metadata(
                cik=latest_10k.cik,
                ticker=latest_10k.ticker,
                company_name=latest_10k.company_name,
                accession_number=latest_10k.accession_number,
                form_type=latest_10k.form_type,
                filing_date=latest_10k.filing_date,
                reporting_period=latest_10k.reporting_period,
                fiscal_year=latest_10k.fiscal_year,
                retrieval_status=latest_10k.retrieval_status,
                primary_document=latest_10k.primary_document,
                filing_url=latest_10k.filing_url,
                submissions_url=latest_10k.submissions_url,
                companyfacts_url=latest_10k.companyfacts_url,
                fetched_at=latest_10k.fetched_at,
                db_path=db_path,
            )
            record_audit_event(
                event_type="SEC_FILING_FETCHED",
                actor="sec_client",
                payload={
                    "ticker": company.ticker,
                    "cik": company.cik,
                    "accession_number": latest_10k.accession_number,
                    "form_type": latest_10k.form_type,
                    "filing_date": latest_10k.filing_date,
                    "reporting_period": latest_10k.reporting_period,
                    "fiscal_year": latest_10k.fiscal_year,
                    "filing_url": latest_10k.filing_url,
                },
                db_path=db_path,
            )

        return SecFilingBundle(
            company=company,
            latest_10k=latest_10k,
            company_facts=company_facts,
            db_filing_id=db_id,
        )
