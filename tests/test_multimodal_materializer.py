import unittest
import asyncio
from unittest.mock import patch

from gateway.services.multimodal_materializer import materialize_multimodal_parts, promote_text_video_links


class MultimodalMaterializerTest(unittest.IsolatedAsyncioTestCase):
    def test_promotes_plain_youtube_url_text_to_video_part(self):
        messages = [{"role": "user", "content": "https://youtu.be/VfGrf5F4Or8?si=l_fNEyH8Y-sWaDjd explain it"}]
        out = promote_text_video_links(messages)
        self.assertIsInstance(out[0]["content"], list)
        self.assertEqual(out[0]["content"][1]["type"], "video_url")

    async def test_keeps_non_multimodal_messages_unchanged(self):
        messages = [{"role": "user", "content": "hello"}]
        out = await materialize_multimodal_parts(
            messages,
            max_image_bytes=1024,
            max_video_bytes=1024,
            max_video_frames=2,
            video_frame_interval_seconds=1.0,
        )
        self.assertEqual(out, messages)

    async def test_expands_video_part_to_images(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe video"},
                    {"type": "video_url", "video_url": {"url": "https://example.com/demo.mp4"}},
                ],
            }
        ]

        async def fake_fetch(_url: str):
            await asyncio.sleep(0)
            return b"video-bytes", "video/mp4"

        async def fake_extract(**_kwargs):
            await asyncio.sleep(0)
            return ["data:image/jpeg;base64,AAA", "data:image/jpeg;base64,BBB"]

        with patch("gateway.services.multimodal_materializer._fetch_bytes_from_url", fake_fetch), patch(
            "gateway.services.multimodal_materializer._extract_video_frame_data_urls", fake_extract
        ):
            out = await materialize_multimodal_parts(
                messages,
                max_image_bytes=5_000_000,
                max_video_bytes=30_000_000,
                max_video_frames=2,
                video_frame_interval_seconds=1.0,
            )

        content = out[0]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[1]["type"], "text")
        self.assertIn("video decoded into 2 frame", content[1]["text"])
        self.assertEqual(content[2], {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAA"}})
        self.assertEqual(content[3], {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,BBB"}})

    async def test_youtube_video_url_path_uses_stream_resolution(self):
        messages = [
            {
                "role": "user",
                "content": [{"type": "video_url", "video_url": {"url": "https://youtu.be/VfGrf5F4Or8"}}],
            }
        ]

        async def fake_resolve(_url: str):
            await asyncio.sleep(0)
            return "https://cdn.example/video.mp4"

        async def fake_extract_from_input(**_kwargs):
            await asyncio.sleep(0)
            return ["data:image/jpeg;base64,AAA"]

        with patch("gateway.services.multimodal_materializer._resolve_youtube_stream_url", fake_resolve), patch(
            "gateway.services.multimodal_materializer._extract_video_frame_data_urls_from_input", fake_extract_from_input
        ):
            out = await materialize_multimodal_parts(
                messages,
                max_image_bytes=5_000_000,
                max_video_bytes=30_000_000,
                max_video_frames=2,
                video_frame_interval_seconds=1.0,
            )

        content = out[0]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[1], {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAA"}})

    async def test_youtube_metadata_fallback_when_decode_fails(self):
        messages = [
            {
                "role": "user",
                "content": [{"type": "video_url", "video_url": {"url": "https://youtu.be/VfGrf5F4Or8"}}],
            }
        ]

        async def fail_resolve(_url: str):
            await asyncio.sleep(0)
            raise RuntimeError("stream_resolve_failed")

        async def fail_download(_url: str):
            await asyncio.sleep(0)
            raise RuntimeError("download_failed")

        async def fake_meta(_url: str):
            await asyncio.sleep(0)
            return "[youtube metadata fallback]\ntitle: demo"

        with patch("gateway.services.multimodal_materializer._resolve_youtube_stream_url", fail_resolve), patch(
            "gateway.services.multimodal_materializer._download_youtube_video_bytes", fail_download
        ), patch("gateway.services.multimodal_materializer._fetch_youtube_metadata_summary", fake_meta):
            out = await materialize_multimodal_parts(
                messages,
                max_image_bytes=5_000_000,
                max_video_bytes=30_000_000,
                max_video_frames=2,
                video_frame_interval_seconds=1.0,
            )
        self.assertEqual(out[0]["content"][0]["type"], "text")
        self.assertIn("youtube metadata fallback", out[0]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
