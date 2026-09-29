from datetime import datetime, time, timedelta

import pytest

from jarvis.brain.timeparse import next_occurrence, parse_reminder, parse_time, repeat_label
from jarvis.core.timeutil import KST

NOW = datetime(2026, 9, 29, 21, 47, tzinfo=KST)  # Tuesday


def at(day_offset, h, m=0):
    d = NOW.date() + timedelta(days=day_offset)
    return datetime(d.year, d.month, d.day, h, m, tzinfo=KST)


@pytest.mark.parametrize(
    "text,when,message",
    [
        ("4시 반에 과제 제출하라고 알려줘", at(1, 4, 30), "과제 제출"),
        ("오후 4시 반에 과제 제출하라고 알려줘", at(1, 16, 30), "과제 제출"),
        ("30분 뒤에 빨래 꺼내라고 해줘", NOW + timedelta(minutes=30), "빨래 꺼내기"),
        ("한 시간 반 뒤에 알려줘", NOW + timedelta(minutes=90), "알림"),
        ("1시간 20분 후에 약 먹으라고 알려줘", NOW + timedelta(minutes=80), "약 먹기"),
        ("10시에 스터디라고 알려줘", at(0, 22), "스터디"),
        ("11시 15분에 엄마한테 전화하라고 알려줘", at(0, 23, 15), "엄마한테 전화"),
        ("내일 아침 7시에 깨워줘", at(1, 7), "일어나기"),
        ("내일 3시에 회의 알려줘", at(1, 15), "회의"),
        ("밤 12시에 자라고 알려줘", at(1, 0), "자기"),
        ("자정에 알림 맞춰줘", at(1, 0), "알림"),
        ("금요일 2시에 도서관 반납하라고 알려줘", at(3, 14), "도서관 반납"),
        ("다음 주 화요일 9시에 발표 준비 알려줘", at(7, 9), "발표 준비"),
    ],
)
def test_one_off_reminders(text, when, message):
    r = parse_reminder(text, NOW)
    assert r is not None, text
    assert (r.when, r.message, r.repeat) == (when, message, None)


@pytest.mark.parametrize(
    "text,rule,first,message",
    [
        ("매일 밤 12시에 잘 준비하라고 알려줘", "daily", at(1, 0), "잘 준비"),
        ("평일 아침 8시에 출석 체크하라고 알려줘", "weekdays", at(1, 8), "출석 체크"),
        ("매주 월요일 10시에 주간 계획 세우라고 알려줘", "weekly:0", at(6, 10), "주간 계획 세우기"),
        ("금요일마다 오후 6시에 빨래하라고 알려줘", "weekly:4", at(3, 18), "빨래"),
    ],
)
def test_repeating_reminders(text, rule, first, message):
    r = parse_reminder(text, NOW)
    assert r is not None
    assert (r.repeat, r.when, r.message) == (rule, first, message)


@pytest.mark.parametrize(
    "text",
    [
        "지금 몇 시야",
        "3시에 스터디 있어?",  # a question, not a request
        "알려줘",  # no time
        "오늘 아침 7시에 깨워줘",  # already past at 21:47
        "음악 틀어줘",
    ],
)
def test_not_reminders(text):
    assert parse_reminder(text, NOW) is None


def test_relative_marks_relative():
    assert parse_time("20분 뒤에", NOW).relative is True
    assert parse_time("9시에", NOW).relative is False


def test_next_occurrence_and_labels():
    assert next_occurrence("weekends", time(9), NOW) == at(4, 9)  # Saturday
    assert next_occurrence("daily", time(21, 50), NOW) == at(0, 21, 50)
    assert repeat_label("weekly:0,2") == "매주 월·수" and repeat_label("weekdays") == "평일"
