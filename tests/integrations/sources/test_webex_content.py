from q99_utils.integrations.sources.webex_content import (
    attachment_decision,
    transcript_decision,
)


def test_attachment_gate_discards_obvious_noise_without_reading_body():
    assert attachment_decision("~$minutes.docx", 100, None).reason == "temporary_or_system_file"
    assert attachment_decision("video.mp4", 100, "video/mp4").reason == "unsupported_format"
    assert attachment_decision("minutes.pdf", 0, "application/pdf").reason == "empty_or_oversized"
    assert attachment_decision("minutes.pdf", 1024, "application/pdf").accepted


def test_transcript_cleanup_preserves_speakers_and_rejects_empty_captions():
    raw = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nAlice: We approved the inspection plan.\nAlice: We approved the inspection plan.\n\nBob: I will send the report tomorrow."
    decision, cleaned = transcript_decision(raw)
    assert decision.accepted
    assert cleaned == (
        "Alice: We approved the inspection plan.\n"
        "Bob: I will send the report tomorrow."
    )
    assert transcript_decision("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi")[0].reason == "empty_or_too_short"
