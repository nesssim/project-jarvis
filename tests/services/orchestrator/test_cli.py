from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from orchestrator.cli import main


def test_cli_exits_when_no_message():
    with (
        patch.object(sys, "argv", ["jarvis-chat"]),
        patch("sys.stdin.read", return_value=""),
        pytest.raises(SystemExit),
    ):
        main()


def test_cli_sends_message_and_streams(tmp_path):
    sse_data = "data: Hello\ndata:  world\ndata: [DONE]\n"
    mock_response = MagicMock()
    mock_response.iter_lines.return_value = sse_data.split("\n")

    mock_client = MagicMock()
    mock_client.__enter__.return_value.stream.return_value.__enter__.return_value = (
        mock_response
    )

    with (
        patch.object(sys, "argv", ["jarvis-chat", "hello"]),
        patch(
            "orchestrator.cli.httpx.Client",
            return_value=mock_client,
        ),
    ):
        main()

    mock_client.__enter__.return_value.stream.assert_called_once_with(
        "POST", "http://localhost:8000/chat", json={"message": "hello"}
    )
