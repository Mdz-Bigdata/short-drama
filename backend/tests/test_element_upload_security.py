import unittest

from app.platform.uploads import UploadValidationError, validate_image_upload


class ElementUploadSecurityTests(unittest.TestCase):
    def test_only_real_bounded_raster_images_are_accepted(self):
        png = b"\x89PNG\r\n\x1a\n" + b"safe-image-bytes"
        self.assertEqual(validate_image_upload("portrait.png", "image/png", png), "image/png")

        with self.assertRaises(UploadValidationError):
            validate_image_upload("payload.png", "image/png", b"<script>alert(1)</script>")
        with self.assertRaises(UploadValidationError):
            validate_image_upload("vector.svg", "image/svg+xml", b"<svg></svg>")
        with self.assertRaises(UploadValidationError):
            validate_image_upload("huge.png", "image/png", png * 1_000_000, max_bytes=1024)


if __name__ == "__main__":
    unittest.main()
