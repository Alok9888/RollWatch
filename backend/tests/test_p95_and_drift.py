from __future__ import annotations

import pytest

from app.prober import (
    build_probe_url,
    calculate_p95,
    compute_headers_hash,
    detect_header_drift,
    detect_version_drift,
)


class TestCalculateP95:
    def test_empty_returns_none(self) -> None:
        assert calculate_p95([]) is None

    def test_single_value(self) -> None:
        assert calculate_p95([42.567]) == 42.57

    def test_exact_percentile_on_sorted_range(self) -> None:
        # 20 values: 10..200 step 10 -> index = 0.95 * 19 = 18.05 -> 190 + 0.05 * 10 = 190.5
        values = [float(i * 10) for i in range(1, 21)]
        assert calculate_p95(values) == 190.5

    def test_unsorted_input_with_outlier(self) -> None:
        values = [500.0, 20.0, 25.0, 22.0, 21.0, 23.0, 24.0, 26.0, 27.0, 28.0]
        p95 = calculate_p95(values)
        assert p95 is not None
        assert p95 > 200.0


class TestDriftDetection:
    def test_headers_hash_case_insensitive_and_selective(self) -> None:
        h1 = compute_headers_hash(
            {
                "Server": "nginx/1.25",
                "Content-Type": "application/json",
                "Cache-Control": "no-store",
                "X-Request-Id": "req-1",
            }
        )
        h2 = compute_headers_hash(
            {
                "server": "  nginx/1.25 ",
                "content-type": "application/json",
                "cache-control": "no-store",
                "X-Request-Id": "req-2",
            }
        )
        assert h1 == h2
        assert not detect_header_drift(h1, h2)

    def test_header_drift_detected_when_tracked_header_changes(self) -> None:
        baseline = compute_headers_hash(
            {"Server": "cloudflare", "Content-Type": "text/html", "Cache-Control": "max-age=60"}
        )
        mutated = compute_headers_hash(
            {"Server": "envoy", "Content-Type": "text/html", "Cache-Control": "max-age=60"}
        )
        assert detect_header_drift(baseline, mutated) is True
        assert detect_header_drift(None, mutated) is False

    @pytest.mark.parametrize(
        ("mode", "expected", "live", "verifying", "expected_drift"),
        [
            ("managed", "abc1234", "abc1234", False, False),
            ("managed", "abc1234", "abc12349999deadbeef", False, False),
            ("managed", "abc12349999deadbeef", "abc1234", False, False),
            ("managed", "abc1234", "def5678", False, True),
            ("managed", "abc1234", "def5678", True, False),
            ("external", "abc1234", "def5678", False, False),
            ("managed", "abc1234", None, False, False),
            ("managed", None, "def5678", False, False),
        ],
    )
    def test_version_drift_rules(
        self,
        mode: str,
        expected: str | None,
        live: str | None,
        verifying: bool,
        expected_drift: bool,
    ) -> None:
        assert detect_version_drift(mode, expected, live, is_verifying=verifying) is expected_drift


class TestBuildProbeUrl:
    def test_preserves_explicit_external_path_with_default_root(self) -> None:
        assert build_probe_url("https://api.github.com/zen", "/") == "https://api.github.com/zen"

    def test_appends_health_path_cleanly(self) -> None:
        assert build_probe_url("https://service.example.com/", "/health") == "https://service.example.com/health"
        assert build_probe_url("https://service.example.com/health", "/health") == "https://service.example.com/health"
