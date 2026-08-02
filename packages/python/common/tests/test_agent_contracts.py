import pytest
from pydantic import ValidationError

from oneiroi_common.agent import AgentMessageContent, AgentRunCreate, DraftProposal


def test_draft_proposal_requires_a_real_change() -> None:
    with pytest.raises(ValidationError):
        DraftProposal()
    proposal = DraftProposal(prompt="A slow camera move", duration=5)
    assert proposal.prompt == "A slow camera move"


def test_agent_message_requires_visible_content() -> None:
    with pytest.raises(ValidationError):
        AgentMessageContent()
    assert AgentMessageContent(text="Visible").text == "Visible"


def test_run_create_is_strict_and_bounded() -> None:
    payload = AgentRunCreate(
        conversationId="conversation-1",
        message="Improve this",
        draftSnapshot={"prompt": "A lake"},
        assetIds=["asset-1"],
    )
    assert payload.draft_snapshot.prompt == "A lake"
    with pytest.raises(ValidationError):
        AgentRunCreate(
            conversationId="conversation-1",
            message="Improve this",
            draftSnapshot={"prompt": "A lake"},
            assetIds=[f"asset-{index}" for index in range(5)],
        )
