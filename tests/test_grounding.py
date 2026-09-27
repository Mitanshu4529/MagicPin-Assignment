"""
Test fact grounding and taboo word suppression.
"""
from composer.grounding import strip_taboos, contains_taboo, format_inr, extract_price_from_title


def test_strip_taboos():
    category = {
        "slug": "dentists",
        "voice": {
            "tone": "peer_clinical",
            "vocab_taboo": ["guaranteed", "100% safe", "completely cure", "miracle"],
        }
    }
    sample_text = "We offer a guaranteed dental whitening with miracle results and a 100% safe procedure."
    cleaned = strip_taboos(sample_text, category)

    assert "guaranteed" not in cleaned.lower()
    assert "miracle" not in cleaned.lower()
    assert "100% safe" not in cleaned.lower()


def test_format_inr():
    assert format_inr(299) == "₹299"
    assert format_inr(1499) == "₹1,499"
    assert format_inr(100000) == "₹1,00,000"


def test_extract_price_from_title():
    assert extract_price_from_title("Dental Cleaning @ ₹299") == "₹299"
    assert extract_price_from_title("First Month @ ₹499 (Tue-Thu)") == "₹499"
    assert extract_price_from_title("Free Consultation") is None
