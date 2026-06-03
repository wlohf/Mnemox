import unittest
from types import SimpleNamespace

import httpx

from app.utils.ai_errors import format_ai_provider_error


class AIErrorMessageTests(unittest.TestCase):
    def test_choices_attribute_error_points_to_openai_compatible_config(self):
        message = format_ai_provider_error(AttributeError("'str' object has no attribute 'choices'"))

        self.assertEqual(
            message,
            "供应商返回的数据格式不对。请检查 Base URL 是否是 OpenAI 兼容的 /v1 地址，模型是否支持聊天接口。",
        )

    def test_http_auth_error_is_user_readable(self):
        response = httpx.Response(
            401,
            json={"error": {"message": "Incorrect API key provided"}},
            request=httpx.Request("GET", "https://example.test/v1/models"),
        )
        error = httpx.HTTPStatusError("auth failed", request=response.request, response=response)

        self.assertEqual(
            format_ai_provider_error(error),
            "API Key 不正确或没有权限。请检查当前供应商的 API Key。",
        )

    def test_openai_style_response_error_message_is_extracted(self):
        error = SimpleNamespace(
            status_code=404,
            response=SimpleNamespace(
                json=lambda: {"error": {"message": "The model does not exist"}},
            ),
        )

        self.assertEqual(
            format_ai_provider_error(error),  # type: ignore[arg-type]
            "模型不存在或当前账号不能使用。请检查模型名称。",
        )


if __name__ == "__main__":
    unittest.main()
