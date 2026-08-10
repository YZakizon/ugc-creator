from app.core.media_naming import generated_media_filename, short_topic_name


def test_generated_media_filename_uses_topic_content_and_output_numbers() -> None:
    assert short_topic_name("Burnout isn't laziness!") == "burnout-isn-t-laziness"
    assert (
        generated_media_filename("Burnout isn't laziness!", 3, 2, ".MP3")
        == "burnout-isn-t-laziness_content3_0002.mp3"
    )
    assert (
        generated_media_filename("Burnout isn't laziness!", 3, 4, "mp4")
        == "burnout-isn-t-laziness_content3_0004.mp4"
    )
