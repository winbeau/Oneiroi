import pytest

from oneiroi_gateway.repositories.studio import InMemoryStudioRepository


@pytest.mark.asyncio
async def test_conversation_put_is_idempotent_and_owner_isolated() -> None:
    repository = InMemoryStudioRepository()
    created = await repository.create_conversation("owner-a", "Original")

    first = await repository.put_conversation("owner-a", created.id, "Updated")
    repeated = await repository.put_conversation("owner-a", created.id, "Updated")

    assert first.id == repeated.id == created.id
    assert len(await repository.list_conversations("owner-a")) == 1
    assert repeated.title == "Updated"
    with pytest.raises(KeyError):
        await repository.get_conversation("owner-b", created.id)
