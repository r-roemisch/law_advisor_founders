from founder_legal_guide.observability import RequestRecord, coverage_status, usage_summary


def record(**kw) -> RequestRecord:
    base = {"question": "q", "strategy": "S1", "mode": "single_pass", "model": "m", "seconds": 2.0}
    return RequestRecord(**{**base, **kw})


def test_gap_signals():
    assert record(citations=0).gap_signal == "no_citations"
    assert record(citations=2, cited_tiers=[3, 3]).gap_signal == "tier3_only"
    assert record(citations=2, cited_tiers=[1, 3]).gap_signal is None
    assert record(citations=0, error="Timeout").gap_signal is None  # failures are not gaps


def test_usage_summary_by_model():
    summary = usage_summary(
        [
            record(
                model="a",
                cost_usd=0.02,
                input_tokens=100,
                output_tokens=10,
                seconds=3,
                escalations=[3],
            ),
            record(
                model="a", cost_usd=0.04, input_tokens=200, output_tokens=20, seconds=5, citations=1
            ),
            record(model="b", cost_usd=None, error="X"),
        ]
    )
    assert summary["requests"] == 3 and summary["errors"] == 1 and summary["escalations"] == 1
    assert summary["cost_usd"] == 0.06
    assert summary["by_model"]["a"] == {
        "requests": 2,
        "cost_usd": 0.06,
        "tokens": 330,
        "median_seconds": 5,
    }


def test_coverage_status_lists_missing_sources():
    cells = [
        {
            "legal_area": "data_protection",
            "jurisdiction": "EU",
            "depth": "deep",
            "required": ["eu-gdpr", "eu-eprivacy"],
        }
    ]
    [cell] = coverage_status(cells, {"eu-gdpr"})
    assert (cell["indexed"], cell["required"], cell["missing"]) == (1, 2, ["eu-eprivacy"])
