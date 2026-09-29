import pytest

from helpers import ctx
from jarvis.brain.router import IntentRouter, squash, strip_wake
from jarvis.core.korean import copula, has_batchim

router = IntentRouter()


def intent(text, **kw):
    r = router.match(text, ctx(**kw))
    return r.intent if r else None


@pytest.mark.parametrize(
    "text",
    ["지금 몇 시야?", "몇시야", "현재 몇 시예요", "시간 알려줘", "헤이 자비스, 지금 몇 시야", "자비스 몇 시지?"],
)
def test_time_queries(text):
    assert intent(text) == "time"


def test_time_reply_grammar():
    assert router.match("몇 시야", ctx(21, 47)).text == "지금은 오후 9시 47분이에요."
    assert router.match("몇 시야", ctx(9, 0)).text == "지금은 오전 9시예요."
    assert router.match("몇 시야", ctx(0, 5)).text == "지금은 오전 12시 5분이에요."


@pytest.mark.parametrize("text", ["오늘 며칠이야?", "오늘 무슨 요일이야", "날짜 알려줘", "오늘 날짜가 뭐야"])
def test_date_queries(text):
    assert intent(text) == "date"


def test_date_reply():
    assert router.match("오늘 며칠이야", ctx()).text == "오늘은 9월 29일 화요일이에요."


@pytest.mark.parametrize(
    "text",
    [
        "3시에 스터디 있어?",  # schedule question, not the clock
        "몇 시에 일어나야 돼",
        "오늘 저녁 메뉴 추천해줘",
        "알림 취소해줘",  # must not be swallowed by the dismiss intent
        "4시 반에 과제 제출하라고 알려줘",
    ],
)
def test_other_things_fall_through_to_llm(text):
    assert intent(text) is None


def test_status_reply_names_problems():
    status = {
        "camera": "off",
        "integrations": {"calendar": "disabled", "gmail": "expired", "ai": "ok"},
        "llm": {"calls": 3},
    }
    text = router.match("시스템 상태 어때", ctx(status=status)).text
    assert text == "카메라는 꺼져 있어요. 캘린더는 아직 연결 전이에요. Gmail은 다시 연결해야 해요. 오늘 AI는 3번 썼어요."


def test_status_all_good():
    status = {"camera": "mock", "integrations": {"calendar": "ok", "ai": "mock"}, "llm": {"calls": 0}}
    assert "연동은 모두 정상이에요" in router.match("상태 알려줘", ctx(status=status)).text


def test_dismiss_is_silent_and_greeting_by_time():
    assert router.match("아니야", ctx()).text == ""
    assert router.match("안녕", ctx(8, 0)).text == "좋은 아침이에요, 재원님."


def test_helpers():
    assert strip_wake("헤이 자비스, 몇 시야") == "몇 시야"
    assert squash("지금 몇 시야?!") == "지금몇시야"
    assert has_batchim("분") and not has_batchim("시")
    assert copula("화요일") == "화요일이에요" and copula("9시") == "9시예요"


def test_particles():
    from jarvis.core.korean import euro, obj, subj

    assert obj("플레이리스트") == "플레이리스트를" and obj("곡") == "곡을"
    assert subj("메일") == "메일이" and subj("슬랙 메시지") == "슬랙 메시지가"
    assert euro("55") == "55로" and euro("30") == "30으로" and euro("서울") == "서울로" and euro("집") == "집으로"
