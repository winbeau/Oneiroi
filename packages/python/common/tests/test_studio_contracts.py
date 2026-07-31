import pytest

from oneiroi_common.studio import ConversationPut, GenerationDraft, JobCreate


def test_job_create_uses_asset_ids_not_server_paths() -> None:
    payload = JobCreate(
        conversationId="conversation-a",
        computeSessionId="compute-a",
        draft={
            "prompt": "A cinematic transition",
            "firstFrameAssetId": "asset-a",
        },
    )

    assert payload.draft.first_frame_asset_id == "asset-a"
    assert "path" not in payload.model_dump_json().lower()


def test_conversation_title_validation_is_bounded() -> None:
    with pytest.raises(ValueError):
        ConversationPut(title="")
    with pytest.raises(ValueError):
        ConversationPut(title="x" * 101)


def test_hq_draft_is_explicit_not_derived_by_fallback() -> None:
    draft = GenerationDraft(prompt="test", queue="hq", profile="hq", resolution="1080p")
    assert draft.profile.value == "hq"
