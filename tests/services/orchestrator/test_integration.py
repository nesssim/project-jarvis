from __future__ import annotations


def test_integration_chat_streams_tokens(test_client, mock_llm):
    mock_llm.tokens = ["Hello", " ", "world!"]
    response = test_client.post("/chat", json={"message": "test message"})

    assert response.status_code == 200
    text = response.text
    assert "Hello" in text
    assert "world!" in text
    assert "[DONE]" in text


def test_integration_chat_validation(test_client):
    response = test_client.post("/chat", json={})
    assert response.status_code == 422

    response = test_client.post("/chat", json={"message": ""})
    assert response.status_code == 422


def test_integration_chat_uses_prompt(test_client, mock_llm, mock_prompt_manager):
    mock_prompt_manager.body = "Custom system prompt for testing"
    test_client.post("/chat", json={"message": "hello"})

    assert mock_llm.captured_kwargs is not None
    msgs = mock_llm.captured_kwargs["messages"]
    assert len(msgs) == 2
    assert msgs[0] == {"role": "system", "content": "Custom system prompt for testing"}
    assert msgs[1] == {"role": "user", "content": "hello"}
