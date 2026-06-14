---
name: "imagegen-preview"
description: "Generate raster images through a project-local .env file using OpenAI-compatible image APIs such as yunwu.ai gpt-image-2, or the system imagegen CLI fallback. Use when the user asks to generate images with a configured third-party image API, gpt-image-2, .env/.env.sample settings, explicit image size/quality/format settings, or an external /v1/images/generations endpoint rather than Codex's built-in image_gen tool."
---

# Imagegen Preview

Use this skill when the user explicitly wants a configured image API/model route instead of the built-in Codex image tool. It is especially useful for OpenAI-compatible providers such as yunwu.ai and for `gpt-image-2` preview endpoints.

The main wrapper is:

```powershell
python $HOME\.codex\skills\imagegen-preview\scripts\run_imagegen_preview.py
```

It supports two transports:

- `http`: direct POST to `<BASE_URL>/images/generations`, using the request field `format`.
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
- Check safe fields only: whether the base URL and API key are configured, model, output path, transport, and duplicate-key warnings.
- Store only the token in `API_KEY`; do not include the `Bearer ` prefix.
- Ensure `.env` is ignored while `.env.sample` remains tracked.
- If duplicate API key lines exist, the script uses the last one and prints a warning without exposing values.

## Workflow

1. Confirm the request needs the configured API/model fallback rather than built-in `image_gen`.
2. Use `scripts/run_imagegen_preview.py`.
3. Start with `--dry-run` to verify payload, transport, and output path.
4. Generate with conservative settings first:
   - `--quality low` or `auto`
   - `--size auto`, `1024x1024`, or a documented landscape size such as `2048x1152`
   - `--format png` unless the user asks for `jpeg` or `webp`
   - For Chinese PPT/explainer images, write the prompt in Chinese and ask for a Chinese-first report layout. Use `--chinese-only` only when the user explicitly requests strict Chinese visible text and there are no source-required Latin terms, acronyms, identifiers, or units.
5. Inspect the generated file with `view_image` or Pillow before reporting success.
6. Report final path, model, size, quality, format, and transport.

## Yunwu gpt-image-2 Notes

For yunwu's `gpt-image-2` image generation endpoint:

- Endpoint: `POST https://yunwu.ai/v1/images/generations`
- Request fields: `model`, `prompt`, `n`, `size`, `quality`, `format`
- Do not send `output_format` to this endpoint.
- Common PPT landscape sizes: `1536x1024`, `2048x1152`, `3840x2160`
- Size constraints usually require both sides to be multiples of 16, max side `<=3840`, aspect ratio `<=3:1`, and total pixels between `655360` and `8294400`.

If the response is `403` with a message like "token has no access to model", the API key is valid enough to reach the service but lacks permission for the selected model. Ask the user to enable the model, change the key, or set `IMAGE_MODEL` to an authorized image model.

## Chinese Explainer Images

When the user asks for PPT-style explanatory images, diagrams, or Chinese-facing visuals, prefer Simplified Chinese narration and layout labels while preserving source-required or domain-standard Latin terms, acronyms, product/model names, code identifiers, and units exactly.

Prompting rules:

- Write the prompt in Chinese.
- Do not treat Chinese style as an English ban. Terms such as `API`, `AI`, `TrafficVLM`, `G40`, `CAN`, `CSV`, `km/h`, model names, file extensions, and code identifiers can be appropriate when they are source content or common technical notation.
- Use `--chinese-only` only for explicit "全中文 / 不要英文缩写 / 中文化所有标签" requests.
- Keep labels short and large; image models often distort dense text.
- Prefer labels such as `后端接口`, `环境初始化`, `仿真接口流程`, `结果表格`, `迁移前先探测`, `自定义工况需重编译`.
- If the user says "全中文", avoid visible Latin terms and acronyms such as `Amesim`, `Skill`, `Python`, `API`, and `CSV`; rewrite them as `仿真软件`, `技能`, `脚本环境`, `接口`, and `结果表格`.
- Avoid asking the image model to render long paragraphs, source code, or many tiny labels.

## Examples

Dry-run:

```powershell
python $HOME\.codex\skills\imagegen-preview\scripts\run_imagegen_preview.py `
  --env .env `
  --prompt "16:9 PPT中文技术讲解图，主题是 Amesim 后端集成 Skill。浅色背景，现代工程风格，四个大模块从左到右：后端接口、Python 环境、Amesim API 流程、结果 CSV 与复用。所有文字清晰、简体中文优先。" `
  --out amesim_skill.png `
  --size 2048x1152 `
  --quality low `
  --format png `
  --dry-run
```

Generate through auto transport:

```powershell
python $HOME\.codex\skills\imagegen-preview\scripts\run_imagegen_preview.py `
  --env .env `
  --prompt "16:9 PPT中文技术讲解图，主题是 Amesim 后端集成 Skill。浅色背景，现代工程风格，四个大模块从左到右：后端接口、Python 环境、Amesim API 流程、结果 CSV 与复用。所有文字清晰、简体中文优先。" `
  --out amesim_skill.png `
  --size 2048x1152 `
  --quality low `
  --format png
```

Force direct HTTP:

```powershell
python $HOME\.codex\skills\imagegen-preview\scripts\run_imagegen_preview.py `
  --transport http `
  --prompt "A clean product mockup on a white background" `
  --out mockup.webp `
  --size 1024x1024 `
  --quality low `
  --format webp
```

Force the system CLI fallback:

```powershell
python $HOME\.codex\skills\imagegen-preview\scripts\run_imagegen_preview.py `
  --transport cli `
  --prompt "1980 New York City yellow taxi, retro film photo, no text" `
  --out nyc_1980.png `
  --size auto `
  --quality low
```
