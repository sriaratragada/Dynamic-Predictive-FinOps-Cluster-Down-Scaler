from freezegun import freeze_time

from controller.predictor import ActivityPredictor

# Fixed reference datetimes (all UTC)
WED_10AM = "2026-05-20 10:00:00"   # Wednesday, inside window
WED_0659 = "2026-05-20 06:59:00"   # Wednesday, before window
WED_1900 = "2026-05-20 19:00:00"   # Wednesday, exactly at end
SAT_10AM = "2026-05-23 10:00:00"   # Saturday, would-be business hour
FRI_2000 = "2026-05-22 20:00:00"   # Friday evening


@freeze_time(WED_10AM)
def test_weekday_in_window_is_active(cfg, mock_prometheus):
    pred = ActivityPredictor(cfg, mock_prometheus)
    assert pred.is_low_activity() is False


@freeze_time(WED_0659)
def test_weekday_before_window_is_idle(cfg, mock_prometheus):
    pred = ActivityPredictor(cfg, mock_prometheus)
    assert pred.is_low_activity() is True


@freeze_time(WED_1900)
def test_weekday_at_exact_end_is_idle(cfg, mock_prometheus):
    # Window is [07:00, 19:00) — 19:00 itself is excluded
    pred = ActivityPredictor(cfg, mock_prometheus)
    assert pred.is_low_activity() is True


@freeze_time(SAT_10AM)
def test_weekend_during_business_hours_is_idle(cfg, mock_prometheus):
    pred = ActivityPredictor(cfg, mock_prometheus)
    assert pred.is_low_activity() is True


@freeze_time(WED_10AM)
def test_minutes_until_active_returns_none_when_already_active(cfg, mock_prometheus):
    pred = ActivityPredictor(cfg, mock_prometheus)
    assert pred.minutes_until_next_active_window() is None


@freeze_time(FRI_2000)
def test_minutes_until_active_friday_evening_jumps_to_monday(cfg, mock_prometheus):
    # Fri 20:00 → Mon 07:00 = 4h + 24h + 24h + 7h = 59h = 3540 min
    pred = ActivityPredictor(cfg, mock_prometheus)
    assert pred.minutes_until_next_active_window() == 3540


def test_metric_override_quiet_day_treated_as_idle(cfg, mock_prometheus):
    cfg.enable_metric_override = True
    mock_prometheus.cluster_cpu_baseline.return_value = 10.0
    mock_prometheus.scalar.return_value = 0.5  # 5% of baseline → idle override
    pred = ActivityPredictor(cfg, mock_prometheus)
    with freeze_time(WED_10AM):
        assert pred.is_low_activity() is True


def test_metric_override_falls_back_to_schedule_on_prometheus_error(cfg, mock_prometheus):
    cfg.enable_metric_override = True
    mock_prometheus.cluster_cpu_baseline.side_effect = Exception("connection refused")
    pred = ActivityPredictor(cfg, mock_prometheus)
    with freeze_time(WED_10AM):
        # Falls back to schedule → inside active window → not idle
        assert pred.is_low_activity() is False


def test_metric_override_normal_usage_stays_active(cfg, mock_prometheus):
    cfg.enable_metric_override = True
    mock_prometheus.cluster_cpu_baseline.return_value = 10.0
    mock_prometheus.scalar.return_value = 5.0  # 50% of baseline → not a quiet day
    pred = ActivityPredictor(cfg, mock_prometheus)
    with freeze_time(WED_10AM):
        assert pred.is_low_activity() is False
