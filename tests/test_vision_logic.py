import pytest

from jarvis.vision.logic import DrowsinessMonitor, PresenceTracker, eye_aspect_ratio, head_down_ratio, is_frontal

OPEN = [(0, 0), (1, -0.3), (2, -0.3), (3, 0), (2, 0.3), (1, 0.3)]
SHUT = [(0, 0), (1, -0.05), (2, -0.05), (3, 0), (2, 0.05), (1, 0.05)]


def test_geometry():
    assert eye_aspect_ratio(OPEN) == pytest.approx(0.2)
    assert eye_aspect_ratio(SHUT) < 0.05
    assert head_down_ratio((0, 0), (10, 0), (5, 9)) == pytest.approx(0.9)
    assert is_frontal((0, 0), (10, 0), (5, 9)) and not is_frontal((0, 0), (10, 0), (9, 9))


def run(monitor, seq, fps=4):
    """seq: list of (seconds, ear). Returns [(t, event)]."""
    out, t = [], 0.0
    for secs, ear in seq:
        for _ in range(int(secs * fps)):
            ev = monitor.feed(t, ear, 0.9, True)
            if ev is not None:
                out.append((round(t, 2), ev))
            t += 1 / fps
    return out


def test_eyes_closed_three_seconds_alerts_then_escalates():
    m = DrowsinessMonitor(baseline_ear=0.2)
    events = run(m, [(1, 0.2), (8.5, 0.05), (1, 0.2)])
    assert [e for _, e in events] == [1, 2, 0]
    assert events[0][0] == pytest.approx(1 + 2.5, abs=0.3)
    assert events[1][0] - events[0][0] == pytest.approx(5, abs=0.3)


def test_blinks_and_short_closures_are_ignored():
    m = DrowsinessMonitor(baseline_ear=0.2)
    seq = []
    for _ in range(20):
        seq += [(0.25, 0.05), (2, 0.2)]  # 250 ms blinks
    seq += [(2.0, 0.05), (1, 0.2)]  # two seconds: still under 2.5 s
    assert run(m, seq) == []


def test_cooldown_after_alert():
    m = DrowsinessMonitor(baseline_ear=0.2, cooldown_sec=60)
    events = run(m, [(3, 0.05), (1, 0.2), (3, 0.05)])
    assert [e for _, e in events] == [1, 0]  # the second closure falls inside the cooldown


def test_head_down_counts_and_side_glance_does_not():
    m = DrowsinessMonitor(baseline_ear=0.2, baseline_pitch=0.9)
    t, fired = 0.0, []
    for _ in range(12):
        ev = m.feed(t, 0.2, 0.3, True)
        fired.append(ev)
        t += 0.25
    assert 1 in fired
    m = DrowsinessMonitor(baseline_ear=0.2)
    assert all(m.feed(i * 0.25, 0.05, 0.9, False) is None for i in range(20))  # not frontal


def test_presence_away_and_return():
    p = PresenceTracker(away_after=20)
    assert p.feed(0, True, False) == ("unknown", "present")
    assert p.feed(10, False, False) is None
    assert p.feed(21, False, False) == ("present", "away")
    assert p.away_since == 0
    assert p.feed(700, True, False) == ("away", "present")


def test_stranger_needs_confirmation_owner_does_not():
    p = PresenceTracker(confirm=1.0)
    p.feed(0, True, False)
    assert p.feed(1, False, True) is None
    assert p.feed(2.2, False, True) == ("present", "stranger")
    assert p.feed(2.5, True, False) == ("stranger", "present")
