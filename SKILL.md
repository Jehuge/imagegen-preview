---
name: "imagegen-preview"
description: "Generate raster images through a project-local .env file using OpenAI-compatible image APIs such as yunwu.ai gpt-image-2. Use when the user asks for a configured third-party image API, gpt-image-2, .env/.env.sample settings, explicit image size/quality/format/timeout controls, or an external /v1/images/generations endpoint rather than Codex's built-in image_gen tool."
---

# Imagegen Preview

Use this skill when the user explicitly wants a configured image API/model route instead of the built-in Codex image tool. It is especially useful for OpenAI-compatible providers such as yunwu.ai and for `gpt-image-2` preview endpoints.

Main wrapper:

```powershell
python $HOME\.codex\skills\imagegen-preview\scripts\run_imagegen_preview.py
```

## Transport

- `http`: direct POST to `<BASE_URL>/images/generations`, using request field `format`.
- `cli`: the system imagegen CLI at `$HOME/.codex/skills/.system/imagegen/scripts/image_gen.py`.

Default `--transport auto` uses direct HTTP for `yunwu.ai` or `gpt-image-2`, because some SDK/CLI stacks pass `output_format`, while yunwu's endpoint expects `format`.

## Config

Look for `.env` in the current workspace unless the user names another file with `--env`.

Create it from `.env.sample`; never commit the real `.env`.

Required values:

```dotenv
BASE_URL=https://yunwu.ai/v1
API_KEY=sk-your-api-key
IMAGE_MODEL=gpt-image-2
OUT_DIR=outputs
```

Accepted aliases:

- `BASE_URL`, `OPENAI_BASE_URL`, or `base_url`
- `API_KEY`, `OPENAI_API_KEY`, or `api_key`
- `IMAGE_MODEL`, `OPENAI_IMAGE_MODEL`, or `image_model`
- `OUT_DIR`, `IMAGEGEN_OUT_DIR`, or `out_dir`

Rules:

- Never print `API_KEY` or the full config file.
- Check safe fields only: base URL host, whether the API key is configured, model, output path, transport, timeout, retry count, and duplicate-key warnings.
- Store only the token in `API_KEY`; do not include the `Bearer ` prefix.
- Ensure `.env`, `.env.*`, and `.imagegen-preview-runs.jsonl` are ignored while `.env.sample` remains tracked.
- If duplicate API key lines exist, the script uses the last one and prints a warning without exposing values.

## Paid Retry Policy

Image APIs can charge even when the client connection is closed before the image response is received. Because of this, live retries are not automatic.

- The script defaults to `--retries 0`.
- A live command with `--retries > 0` now requires `--allow-paid-retry`.
- Do not use `--allow-paid-retry` unless the user explicitly accepts that a disconnected attempt may still be billed.
- Each HTTP run writes a safe JSONL entry to `.imagegen-preview-runs.jsonl` unless `--no-log` is set. The log excludes API keys and full prompts; it records model, size, quality, attempts, elapsed time, output path, and error text for billing/debug reconciliation.

## Workflow

1. Confirm the request needs the configured API/model path rather than built-in `image_gen`.
2. Use `scripts/run_imagegen_preview.py`.
3. Start with `--dry-run` to verify payload, transport, timeout, retry count, paid-retry acknowledgement, log path, and output path.
4. Generate with stable settings first:
   - PPT/slide supporting images: prefer `--size 2048x1152 --quality medium --format png`.
   - 4K landscape: prefer `--size 3840x2160 --quality low --format png`.
   - Use `--timeout 300` for 2K/4K jobs.
   - Use `--quality high` only when the user explicitly asks for it.
   - For yunwu `gpt-image-2`, `quality=high` has been observed to disconnect after billing at both `2048x1152` and `3840x2160`. Try it once without retries; if it disconnects, explain the risk before any further paid attempt.
5. Inspect the generated file with `view_image` or Pillow before reporting success.
6. Report final path, model, size, quality, format, transport, timeout, retry count, and whether a paid retry was allowed.

## Yunwu gpt-image-2 Notes

For yunwu's `gpt-image-2` image generation endpoint:

- Endpoint: `POST https://yunwu.ai/v1/images/generations`
- Request fields: `model`, `prompt`, `n`, `size`, `quality`, `format`
- Do not send `output_format` to this endpoint.
- Common landscape sizes: `1536x1024`, `2048x1152`, `3840x2160`
- Size constraints usually require both sides to be multiples of 16, max side `<=3840`, aspect ratio `<=3:1`, and total pixels between `655360` and `8294400`.
- The wrapper defaults to a 300-second HTTP timeout.

If the response is `403` with a message like "token has no access to model", the API key is valid enough to reach the service but lacks permission for the selected model. Ask the user to enable the model, change the key, or set `IMAGE_MODEL` to an authorized image model.

If the response is `401` with a message like "invalid token", the endpoint was reached but the API key is not valid for that provider. Ask the user to set a valid provider key in `.env`.

If the connection ends with `RemoteDisconnected`, distinguish two facts:

- Local fact: no image response was received, so no high-quality output can be saved unless the provider console exposes a recoverable URL/response.
- Billing fact: the provider may still have processed and charged the request.

Ask the user to check the provider console details for a response URL or request id before retrying.

## Chinese Explainer Images

When the user asks for PPT-style explanatory images, diagrams, or Chinese-facing visuals, prefer Simplified Chinese narration and layout labels while preserving source-required or domain-standard Latin terms, acronyms, product/model names, code identifiers, and units exactly.

Prompting rules:

- Write the prompt in Chinese when visible Chinese labels are desired.
- Do not treat Chinese style as an English ban. Terms such as `API`, `AI`, `TrafficVLM`, `G40`, `CAN`, `CSV`, `km/h`, model names, file extensions, and code identifiers can be appropriate when they are source content or common technical notation.
- Use `--chinese-only` only for explicit "all visible text must be Simplified Chinese" requests.
- Keep labels short and large; image models often distort dense text.
- Avoid asking the image model to render long paragraphs, source code, or many tiny labels.

## Examples

PPT 2K stable generate:

```powershell
python $HOME\.codex\skills\imagegen-preview\scripts\run_imagegen_preview.py `
  --env .env `
  --transport http `
  --prompt "16:9 high-end PPT supporting illustration for smart mobility last-kilometer navigation, no readable text, no logos, no watermark" `
  --out last-mile-navigation-ppt-2k.png `
  --size 2048x1152 `
  --quality medium `
  --format png `
  --timeout 300
```

High quality single attempt:

```powershell
python $HOME\.codex\skills\imagegen-preview\scripts\run_imagegen_preview.py `
  --env .env `
  --transport http `
  --prompt "Cinematic 16:9 futuristic city skyline with flying cars, no readable text, no logos, no watermark" `
  --out future-city-2k-high.png `
  --size 2048x1152 `
  --quality high `
  --format png `
  --timeout 300
```

Paid retry only after explicit user acceptance:

```powershell
python $HOME\.codex\skills\imagegen-preview\scripts\run_imagegen_preview.py `
  --env .env `
  --transport http `
  --prompt "Cinematic 16:9 futuristic city skyline with flying cars, no readable text, no logos, no watermark" `
  --out future-city-2k-high.png `
  --size 2048x1152 `
  --quality high `
  --format png `
  --timeout 300 `
  --retries 1 `
  --allow-paid-retry
```
