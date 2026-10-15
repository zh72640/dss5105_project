"""Diagnose configured Gemini model visibility vs generation access, without logging secrets."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.core.providers.llm_client import BackendError, LLMBackend, GEMINI_BASE_URL, gemini_model


def diagnose():
    try:
        model_name = gemini_model()
    except BackendError as error:
        return {'model': None, 'base_url': GEMINI_BASE_URL, 'api_version': 'v1beta',
                'model_lookup_http': None, 'generate_http': None, 'diagnosis': 'NOT_RUN',
                'error': str(error)}
    result = {'model': model_name, 'base_url': GEMINI_BASE_URL, 'api_version': 'v1beta',
              'model_lookup_http': None, 'generate_http': None, 'diagnosis': 'NOT_RUN'}
    try:
        backend = LLMBackend()
    except BackendError as error:
        return {**result, 'error': str(error)}
    try:
        try:
            model = backend.client.models.get(model=backend.model)
            result.update(model_lookup_http=200, model_visible=True,
                          generate_content_advertised='generateContent' in (model.supported_actions or []))
        except backend._api_error as error:
            result.update(model_lookup_http=error.code, model_visible=False,
                          diagnosis='MODEL_LOOKUP_FAILED')
            # Do not consume generation quota when even the exact-model lookup fails.
            return result
        # Minimal request: no order data, parser prompt, JSON Schema or thinking setting.
        try:
            backend.client.models.generate_content(
                model=backend.model, contents='Reply with OK.',
                config=backend.types.GenerateContentConfig(max_output_tokens=32),
            )
            result.update(generate_http=200, diagnosis='MINIMAL_GENERATION_SUCCEEDED')
        except backend._api_error as error:
            result.update(generate_http=error.code,
                          diagnosis='MODEL_ACCESS_OR_SERVICE_ROUTE' if error.code == 404 else 'GENERATION_FAILED')
        return result
    except (backend._transport_error, OSError, TimeoutError):
        return {**result, 'diagnosis': 'CONNECTION_FAILED'}
    finally:
        backend.close()


def main():
    result = diagnose()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print('模型列表/查询可见不等于有生成权限。此命令不显示密钥、原始服务错误或项目标识。')
    return 0 if result['diagnosis'] == 'MINIMAL_GENERATION_SUCCEEDED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
