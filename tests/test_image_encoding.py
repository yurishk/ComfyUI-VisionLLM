from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image

from conftest import nodes


def decode_data_url(url: str) -> tuple[str, Image.Image]:
    header, encoded = url.split(",", 1)
    image = Image.open(io.BytesIO(base64.b64decode(encoded)))
    image.load()
    return header, image


def test_small_image_stays_lossless_png():
    image = np.zeros((1, 512, 768, 3), dtype=np.float32)

    header, encoded = decode_data_url(nodes._encode_images(image)[0])

    assert header == "data:image/png;base64"
    assert encoded.size == (768, 512)


def test_large_image_is_resized_and_compressed():
    rng = np.random.default_rng(7)
    image = rng.random((1, 2600, 1900, 3), dtype=np.float32)

    header, encoded = decode_data_url(nodes._encode_images(image)[0])

    assert header == "data:image/jpeg;base64"
    assert max(encoded.size) <= nodes.AUTO_IMAGE_MAX_EDGE
    assert encoded.width * encoded.height <= nodes.AUTO_IMAGE_MAX_PIXELS


def test_complex_image_can_trigger_payload_limit_without_resize():
    rng = np.random.default_rng(11)
    image = rng.random((1, 2048, 2048, 3), dtype=np.float32)

    header, encoded = decode_data_url(nodes._encode_images(image)[0])

    assert header == "data:image/jpeg;base64"
    assert encoded.size == (2048, 2048)
