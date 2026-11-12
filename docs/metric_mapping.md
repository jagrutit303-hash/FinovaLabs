# FinovaLabs — Approved 8-Metric XBRL Mapping Specification

**AI-Powered Financial Filing Auditor**  
*(Synchronized with `src/finova_labs/metric_mapping.py`)*

| # | Metric Name | Period Type | Expected Unit | Sign Convention | Primary US-GAAP Concepts (`us-gaap:*`) |
| --- | --- | --- | --- | --- | --- |
| 1 | **Revenue** | `duration` | `USD` | `positive` | `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet`, `SalesRevenueGoodsNet`, `RevenueFromContractWithCustomerIncludingAssessedTax` |
| 2 | **Net Income** | `duration` | `USD` | `signed` | `NetIncomeLoss`, `ProfitLoss`, `NetIncomeLossAvailableToCommonStockholdersBasic` |
| 3 | **Total Assets** | `instant` | `USD` | `positive` | `Assets` |
| 4 | **Total Liabilities** | `instant` | `USD` | `positive` | `Liabilities` *(escalated to Human Review as `MISSING` if issuer omits standalone subtotal tag, e.g., `AMZN`, `WMT`)* |
| 5 | **Shareholders' Equity** | `instant` | `USD` | `signed` | `StockholdersEquity`, `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` |
| 6 | **Operating Cash Flow** | `duration` | `USD` | `signed` | `NetCashProvidedByUsedInOperatingActivities`, `NetCashProvidedByUsedInOperatingActivitiesContinuingOperations` |
| 7 | **Cash and Cash Equivalents** | `instant` | `USD` | `positive` | `CashAndCashEquivalentsAtCarryingValue`, `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents` |
| 8 | **Earnings Per Share** | `duration` | `USD/shares` | `signed` | `EarningsPerShareDiluted`, `EarningsPerShareBasic` |
