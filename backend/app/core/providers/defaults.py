"""Default addresses and model ids for every external provider.

A provider's address is written here once. The model configuration center, the
environment-configured gateway and the provider clients all read it from this
module, so a vendor moving its API cannot leave two callers disagreeing. Every
value is a fallback only: a saved model configuration or the matching
environment variable always wins.
"""

from __future__ import annotations

from typing import Final


ARK_BASE_URL: Final = "https://ark.cn-beijing.volces.com/api/v3"
DEEPSEEK_API_ROOT: Final = "https://api.deepseek.com"
GEMINI_API_ROOT: Final = "https://generativelanguage.googleapis.com"
MINIMAX_API_ROOT: Final = "https://api.minimaxi.com"
MINIMAX_H3_PATH: Final = "/v2/video_generation"
MINIMAX_H3_STATUS_PATH_TEMPLATE: Final = "/v2/query/video_generation/{task_id}"
MINIMAX_FILES_PATH: Final = "/v1/files/retrieve"

# Keyed by the provider id used in the model configuration center.
PROVIDER_DEFAULT_BASE_URLS: Final[dict[str, str]] = {
    "deepseek": DEEPSEEK_API_ROOT,
    "volcengine": ARK_BASE_URL,
    "seedance": ARK_BASE_URL,
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "gemini": f"{GEMINI_API_ROOT}/v1beta/openai",
    "openai": "https://api.openai.com/v1",
    "agnes": "https://apihub.agnes-ai.com/v1",
    "minimax": MINIMAX_API_ROOT,
    "kling": "https://api-singapore.klingai.com",
    "xai": "https://api.x.ai",
    "fal": "https://queue.fal.run",
    "ltx": "https://api.ltx.io",
    "elevenlabs": "https://api.elevenlabs.io",
}

# The environment-configured gateway predates the configuration center and
# addresses two providers differently: DeepSeek through its versioned path and
# Gemini through its native API root instead of the OpenAI-compatible one.
GATEWAY_DEFAULT_BASE_URLS: Final[dict[str, str]] = {
    "deepseek": f"{DEEPSEEK_API_ROOT}/v1",
    "seedance": PROVIDER_DEFAULT_BASE_URLS["seedance"],
    "qwen": PROVIDER_DEFAULT_BASE_URLS["qwen"],
    "gemini": GEMINI_API_ROOT,
    "agnes": PROVIDER_DEFAULT_BASE_URLS["agnes"],
}

# Model ids the gateway uses when neither the environment nor config.json names one.
GATEWAY_DEFAULT_MODELS: Final[dict[str, str]] = {
    "deepseek": "deepseek-chat",
    "seedance": "seedance-llm",
    "seedance_image": "doubao-seedream-4-5-251128",
    "qwen": "qwen-turbo",
    "gemini": "gemini-3.1-pro-image",
    "agnes": "agnes-2.0-flash",
    "agnes_image": "agnes-image-2.1-flash",
    "agnes_video": "agnes-video-v2.0",
}

# Seedream 4.5 requires at least 3,686,400 pixels; this is 9:16 portrait and qualifies.
DEFAULT_SEEDANCE_IMAGE_SIZE: Final = "1440x2560"

# Clips are requested in the frame the final cut is delivered in.
DEFAULT_ASPECT_RATIO: Final = "9:16"
DEFAULT_VIDEO_RESOLUTION: Final = "1080p"
# Seedance previews at 720p by default; the compositor conforms every clip to the master.
SEEDANCE_DEFAULT_RESOLUTION: Final = "720p"
# How long an asynchronous video job may run, and how often it is polled.
DEFAULT_VIDEO_WAIT_SECONDS: Final = 900
DEFAULT_VIDEO_POLL_SECONDS: Final = 5
# Hosts served by Volcengine Ark, for the Ark-only proxy.
ARK_HOST_SUFFIX: Final = "volces.com"


def default_base_url(provider: str) -> str:
    return PROVIDER_DEFAULT_BASE_URLS[provider]
