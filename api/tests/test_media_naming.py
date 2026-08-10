from app.core.media_naming import generated_media_filename, short_topic_name


def test_generated_media_filename_uses_topic_content_and_output_numbers() -> None:
    assert short_topic_name("Burnout isn't laziness!") == "burnout-isn-t-laziness"
    assert (
        generated_media_filename("Burnout isn't laziness!", 3, 2, "audio", ".MP3")
        == "burnout-isn-t-laziness_content3_2-audio.mp3"
    )
    assert (
        generated_media_filename("Burnout isn't laziness!", 3, 4, "video", "mp4")
        == "burnout-isn-t-laziness_content3_4-video.mp4"
    )
