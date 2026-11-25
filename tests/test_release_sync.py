from pathlib import Path

from src.services.release_sync import check_for_update, published_version, resolve_app_exe, write_manifest


def _touch(path: Path, payload: bytes = b"exe") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_launcher_copies_the_newer_release_from_the_share(tmp_path: Path):
    share = tmp_path / "share"
    local = tmp_path / "local"
    _touch(share / "releases" / "0.0.1" / "GrandSummary" / "GrandSummary.exe", b"old")
    _touch(share / "releases" / "0.0.2" / "GrandSummary.exe", b"new")
    write_manifest(share, "0.0.1")
    _touch(local / "releases" / "0.0.1" / "GrandSummary.exe", b"old")
    write_manifest(local, "0.0.1")

    exe = resolve_app_exe(dist=share, app_root=local)

    assert exe == local / "releases" / "0.0.2" / "GrandSummary.exe"
    assert exe.read_bytes() == b"new"
    assert not (local / "releases" / "0.0.1").exists()
    assert published_version(share) == "0.0.2"
    assert check_for_update(share) == ("0.0.1", "0.0.2")


def test_older_share_does_not_replace_the_local_release(tmp_path: Path):
    share = tmp_path / "share"
    local = tmp_path / "local"
    _touch(share / "releases" / "0.0.1" / "GrandSummary.exe", b"share")
    write_manifest(share, "0.0.1")
    kept = local / "releases" / "0.0.3" / "GrandSummary.exe"
    _touch(kept, b"local")
    write_manifest(local, "0.0.3")

    assert resolve_app_exe(dist=share, app_root=local) == kept
    assert kept.read_bytes() == b"local"
