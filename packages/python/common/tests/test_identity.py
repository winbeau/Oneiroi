from oneiroi_common.identity import owner_id_for_access_subject


def test_access_owner_mapping_is_stable_and_scoped_by_issuer_subject() -> None:
    first = owner_id_for_access_subject("https://team.cloudflareaccess.com/", "user-a")

    assert first == owner_id_for_access_subject("https://team.cloudflareaccess.com", "user-a")
    assert first != owner_id_for_access_subject("https://team.cloudflareaccess.com", "user-b")
    assert first != owner_id_for_access_subject("https://other.cloudflareaccess.com", "user-a")
    assert len(first) < 128
