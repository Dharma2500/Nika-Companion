from nika.dashboard import render_dashboard


def test_dashboard_has_native_protected_dual_key_form_and_optional_lm_studio() -> None:
    page = render_dashboard("A" * 32).decode("utf-8")

    assert 'action="/dashboard/api/openai-credentials"' in page
    assert 'name="primary_key" type="password"' in page
    assert 'name="secondary_key" type="password"' in page
    assert 'name="action" value="save"' in page
    assert 'name="action" value="test"' in page
    assert "gpt-6-luna" in page
    assert "OpenAI-compatible / LM Studio" in page
    assert "localStorage" not in page
    assert "sessionStorage" not in page
    assert "primary_key" not in page[page.index("<script"):]


def test_dashboard_requires_a_valid_nonce() -> None:
    import pytest

    with pytest.raises(ValueError, match="nonce"):
        render_dashboard("invalid")
