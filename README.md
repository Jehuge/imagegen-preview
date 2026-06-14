# imagegen-preview

Codex skill for generating raster images through a project-local `.env` file and OpenAI-compatible image APIs. It is tuned for `gpt-image-2` preview endpoints such as yunwu.ai while keeping a CLI fallback to Codex's bundled image generation helper.

## Install

Clone this repository into your Codex skills directory:

```powershell
git clone https://github.com/Jehuge/imagegen-preview.git $HOME\.codex\skills\imagegen-preview
```

If the skill already exists, back up your local changes first, then pull or replace the directory.

## Configure

Copy `.env.sample` to `.env` in the workspace where you want to generate images:

```dotenv
BASE_URL=https://yunwu.ai/v1
API_KEY=sk-your-api-key
IMAGE_MODEL=gpt-image-2
OUT_DIR=outputs
```

The real `.env` is intentionally ignored by git. Do not include `Bearer ` in `API_KEY`.

## Usage

Dry-run first:

```powershell
python $HOME\.codex\skills\imagegen-preview\scripts\run_imagegen_preview.py `
  --env .env `
  --prompt "A clean product mockup on a white background" `
  --out mockup.png `
  --size 1024x1024 `
  --quality low `
  --format png `
  --dry-run
```

Generate:

```powershell
python $HOME\.codex\skills\imagegen-preview\scripts\run_imagegen_preview.py `
  --env .env `
  --prompt "A clean product mockup on a white background" `
  --out mockup.png `
  --size 1024x1024 `
  --quality low `
  --format png
```

2K/4K requests can take longer. The HTTP wrapper defaults to a 300-second timeout.

For yunwu `gpt-image-2`, `quality=high` may disconnect after the provider has processed or billed the request. Retry only when you explicitly accept that a second paid request may be created:

```powershell
python $HOME\.codex\skills\imagegen-preview\scripts\run_imagegen_preview.py `
  --env .env `
  --transport http `
  --prompt "Cinematic 4K 16:9 futuristic city skyline with flying cars, no text" `
  --out future-city-flying-cars-4k.png `
  --size 2048x1152 `
  --quality medium `
  --format png `
  --timeout 300
```

Live retries require `--allow-paid-retry`.

The wrapper also defaults to edge-to-edge scene output. It appends a guard against poster borders, top/bottom bars, letterboxing, slide canvases, and presentation mats. Use `--allow-frame` only when you explicitly want a framed or bordered composition.

## Files

- `SKILL.md`: Codex skill instructions.
- `scripts/run_imagegen_preview.py`: wrapper for HTTP or CLI generation.
- `agents/openai.yaml`: display metadata for the skill.
- `.env.sample`: safe configuration template.
