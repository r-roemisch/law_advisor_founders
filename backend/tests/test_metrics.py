from founder_legal_guide.evaluation import metrics

from .conftest import FakeModels


def judge(reply):
    return FakeModels(utility=lambda system, user: reply).chat("judge")


def test_context_precision_is_average_precision_over_ranks():
    # useful at ranks 1 and 3: (1/1 + 2/3) / 2
    assert metrics.context_precision(judge([1, 0, 1]), "q", "ref", ["a", "b", "c"]) == 0.833
    assert metrics.context_precision(judge([0, 0]), "q", "ref", ["a", "b"]) == 0.0
    assert metrics.context_precision(judge("not a list"), "q", "ref", ["a"]) is None


def test_faithfulness_is_the_supported_share_of_claims():
    replies = iter([["claim one", "claim two"], [1, 0]])
    fake = FakeModels(utility=lambda system, user: next(replies)).chat("judge")
    assert metrics.faithfulness(fake, "answer", ["context"]) == 0.5
