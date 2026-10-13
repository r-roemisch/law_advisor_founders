import pytest

from founder_legal_guide.answering.guard import check_question, redact

from .conftest import FakeModels


@pytest.mark.parametrize(
    ("text", "kind", "replacement"),
    [
        ("Our employee anna.schmidt@example.com leaked data", "email", "[email removed]"),
        ("Call me at +49 30 12345678 please", "phone", "[phone number removed]"),
        ("Rückruf unter 0151 2345 6789", "phone", "[phone number removed]"),
        ("IBAN DE89 3704 0044 0532 0130 00 was charged", "iban", "[IBAN removed]"),
        ("card 4111 1111 1111 1111 expired", "card", "[card number removed]"),
    ],
)
def test_personal_data_is_removed(text, kind, replacement):
    clean, found = redact(text)
    assert kind in found and replacement in clean


@pytest.mark.parametrize(
    "text",
    [
        "Does Art. 6(1)(f) GDPR apply under Regulation (EU) 2016/679?",
        "CELEX 32016R0679 and Directive 2019/790, § 312k BGB",
        "Revenue of $26,625,000 and 100000 consumers, HRB 123456",
        "Deadline 2027-12-02 or 02.12.2027",
    ],
)
def test_legal_citations_and_numbers_are_not_mistaken_for_personal_data(text):
    assert redact(text) == (text, [])


def test_model_classification_is_used_when_valid():
    models = FakeModels(utility=lambda system, user: {"triggers": [3, 7], "tax_question": False})
    result = check_question("We had an incident", models.chat("utility"))
    assert [t.id for t in result.triggers] == [3, 7] and result.method == "model"
    assert "FIRST" in result.instructions()


def test_keywords_take_over_when_the_model_fails():
    models = FakeModels(utility=lambda system, user: "nonsense")
    result = check_question(
        "Wir haben eine Abmahnung bekommen und eine Datenpanne. Was ist mit der Umsatzsteuer?",
        models.chat("utility"),
    )
    assert result.method == "keywords"
    assert {t.id for t in result.triggers} == {1, 3}
    assert result.tax_question
    assert "tax advisor" in result.instructions()


def test_general_questions_trigger_nothing_without_a_model():
    result = check_question("What is a GmbH?", None)
    assert result.triggers == [] and not result.tax_question and result.instructions() == ""
