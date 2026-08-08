import pytest

from app.core.urls import validate_render_node_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8188",
        "http://10.0.0.10:8188",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]:8188",
        "http://localhost:8188",
    ],
)
def test_render_node_url_blocks_private_and_metadata_destinations(url: str) -> None:
    with pytest.raises(ValueError, match="private network"):
        validate_render_node_url(url)


def test_render_node_url_allows_explicit_private_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMFYUI_ALLOWED_HOSTS", "gpu-comfy.internal")

    assert (
        validate_render_node_url("http://gpu-comfy.internal:8188")
        == "http://gpu-comfy.internal:8188"
    )


def test_render_node_url_allows_public_literal() -> None:
    assert validate_render_node_url("https://8.8.8.8:8188") == "https://8.8.8.8:8188"
