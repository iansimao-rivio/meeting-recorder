# Meeting Recorder

A Linux desktop applet that records meetings, transcribes them, and generates structured notes — all in a few clicks. Supports both cloud and local processing, with 100+ AI providers via LiteLLM.

## Features

- **Record** system audio + microphone simultaneously, with optional separate tracks for better diarization
- **Transcribe** with Google Gemini, ElevenLabs Scribe v2, local Whisper, or 100+ providers via LiteLLM
- **Summarize** with Claude Code CLI (subscription), or any LLM via LiteLLM (Gemini, Ollama, OpenAI, Anthropic, OpenRouter, etc.)
- **LiteLLM integration** — unified access to 100+ LLM providers with a single model string
- **Local models** — run fully offline with Whisper + Ollama, no API key required
- **Multi-platform** — Debian/Ubuntu (PulseAudio) and Arch Linux (PipeWire/Wayland)
- **Screen recording** — per-monitor Wayland-native recording via gpu-screen-recorder
- **API key store** — manage all provider API keys in Settings
- **Customizable prompts** — edit transcription and summarization prompts in Settings
- **System tray** integration (AppIndicator / pystray fallback) with custom icon and recording indicator
- **Call detection** — optionally monitor for active calls and get notified to start recording
- **Start at system startup** — optionally launch automatically on login
- **Organized output** — files saved in a dated hierarchy under your chosen output folder

## Output Structure

Each recording session creates a folder:

```
~/meetings/
└── 2026/
    └── March/
        └── 04/
            └── 14-30_Standup/
                ├── recording.mp3         # Combined audio
                ├── recording_mic.mp3     # Microphone track (if separate tracks enabled)
                ├── recording_system.mp3  # System audio track (if separate tracks enabled)
                ├── screen-eDP-1.mp4      # Screen recording (if enabled)
                ├── transcript.md
                └── notes.md
```

When using "Use Existing Recording", transcript and notes are saved next to the selected file.

## Requirements

### Debian/Ubuntu

- Debian/Ubuntu-based Linux (tested on Ubuntu 22.04+)
- System packages installed by `install.sh`: `ffmpeg`, `pulseaudio-utils`, `pipewire-pulse`, Python 3 with GTK3 bindings
- Python packages (installed into a venv): see `requirements.txt`

### Arch Linux

- Arch Linux with KDE Plasma / Wayland (tested on Plasma 6)
- System packages installed by `install/install-arch.sh`: `ffmpeg`, `pipewire`, `pipewire-pulse`, `wireplumber`, Python 3 with GTK3 bindings
- Optional: `gpu-screen-recorder` (AUR) for screen recording

### Provider Requirements

| Provider | Requirement |
|---|---|
| **Gemini** (transcription or summarization via LiteLLM) | API key from [aistudio.google.com](https://aistudio.google.com) |
| **ElevenLabs Scribe v2** (transcription) | API key from [elevenlabs.io](https://elevenlabs.io) |
| **Whisper** (local transcription) | Model downloaded from HuggingFace (~500 MB – 3 GB); NVIDIA GPU optional |
| **Ollama** (local summarization via LiteLLM) | [Ollama](https://ollama.com) installed and running (`ollama serve`) |
| **Claude Code CLI** (summarization) | [Claude Code](https://claude.ai/claude-code) installed and on PATH |
| **LiteLLM** (any other provider) | Appropriate API key set in Settings → API Keys |

## Installation

### Option 1: .deb package (Debian/Ubuntu, recommended)

Download the latest `.deb` from the [Releases](../../releases) page and install it:

```bash
sudo dpkg -i meeting-recorder_*.deb
sudo apt-get install -f   # installs any missing dependencies
```

The installer sets up all system dependencies, creates a Python venv at `/opt/meeting-recorder/venv`, and installs Ollama if not already present.

To uninstall:

```bash
sudo apt remove meeting-recorder
```

### Option 2: install.sh (Debian/Ubuntu, from source)

```bash
git clone <repo-url>
cd meeting-recorder
./install.sh
```

### Option 3: install-arch.sh (Arch Linux)

```bash
git clone <repo-url>
cd meeting-recorder
install/install-arch.sh
```

Installs system deps via pacman, sets up a Python venv via uv, and auto-installs gpu-screen-recorder from AUR if yay/paru is available.

### Uninstall

```bash
./uninstall.sh
```

> Your recordings (`~/meetings/`) and config (`~/.config/meeting-recorder/`) are preserved.

Then launch either way:

```bash
meeting-recorder
# or from your application menu: "Meeting Recorder"
```

> **GNOME users:** System tray requires the AppIndicator extension:
> ```bash
> sudo apt install gnome-shell-extension-appindicator
> gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com
> ```

## Running from Source

```bash
cd meeting-recorder
python3 -m venv .venv --system-site-packages
.venv/bin/pip install -r requirements.txt
PYTHONPATH=src python3 -m meeting_recorder
```

## Recording Modes

| Mode | What is captured | When to use |
|------|-----------------|-------------|
| **Record (Headphones)** | Microphone + system audio (calls, browser, etc.) | You're wearing headphones — no echo risk |
| **Record (Speaker)** | Microphone only | Laptop speakers — avoids loopback echo |

## Services

### Transcription

| Provider | How it works | Requires |
|---|---|---|
| **Google Gemini** | Audio uploaded directly to Gemini multimodal API | API key |
| **ElevenLabs Scribe v2** | Audio sent to ElevenLabs API, native diarization (up to 32 speakers) | API key |
| **Whisper** | Runs locally on your machine via faster-whisper | Model downloaded in Settings → Model Config |
| **LiteLLM** | Routes to any supported STT provider (Groq, OpenAI, Deepgram, etc.) | Provider API key |

### Summarization

| Provider | How it works | Requires |
|---|---|---|
| **Claude Code CLI** | Shells out to `claude --print`, uses your Claude Code subscription | Claude Code installed |
| **LiteLLM** | Routes to any LLM (Gemini, Ollama, OpenAI, Anthropic, OpenRouter, etc.) | Provider API key (or Ollama running locally) |

Mix and match freely — e.g. Whisper for transcription + Ollama via LiteLLM for summarization runs fully offline with no API key.

### LiteLLM Model Strings

LiteLLM routes to providers via the model string prefix:

```
gemini/gemini-2.5-flash          # Google Gemini
ollama/phi4-mini                 # Local Ollama
openai/gpt-4o                    # OpenAI
anthropic/claude-sonnet-4-latest # Anthropic
openrouter/anthropic/claude-sonnet-4  # OpenRouter
groq/whisper-large-v3            # Groq (transcription)
```

Select from curated lists in Settings, or type any `provider/model` string.

## First-Time Setup

Open **Settings** (gear icon or tray menu):

1. **General tab** — choose your transcription and summarization providers; set output folder and recording quality. When LiteLLM is selected, a model dropdown with free-text entry appears.
2. **Platform tab** — choose audio backend (PulseAudio/PipeWire), enable separate audio tracks, configure screen recording.
3. **Model Config tab** — configure direct provider models:
   - *Gemini*: choose a model
   - *Whisper*: select a model and click Download
   - *Ollama*: set host, select or type a model name, click Pull Model to download
4. **API Keys tab** — add API keys for your providers (Gemini, OpenAI, ElevenLabs, etc.). Keys take effect immediately after saving.
5. **Prompts tab** — optionally customize the transcription or summarization prompt

## Settings Reference

### General tab

| Setting | Description |
|---|---|
| Transcription provider | Google Gemini, ElevenLabs Scribe v2, Whisper (local), or LiteLLM |
| Summarization provider | Claude Code CLI or LiteLLM |
| LiteLLM model | Model string (visible when LiteLLM selected) — curated list + free-text entry |
| Output folder | Where recordings and notes are saved (default: `~/meetings`) |
| Recording quality | Audio bitrate preset (Very High / High / Medium / Low) |
| Processing timeout | Max time to wait for provider response (1–10 min) |
| Start at system startup | Launch automatically on login |
| Enable call detection | Monitor for active calls and notify you to start recording |

### Platform tab

| Setting | Description |
|---|---|
| Audio backend | PulseAudio or PipeWire |
| Separate audio tracks | Record mic and system audio as independent files |
| Screen recording | Enable per-monitor screen recording (requires gpu-screen-recorder) |
| Screen recorder | gpu-screen-recorder or none |
| Monitors | "all" or comma-separated monitor names |
| FPS | Screen recording frame rate (1–60) |

### Model Config tab

**Gemini**

| Setting | Description |
|---|---|
| Model | Gemini model to use for direct transcription (`gemini-flash-latest` recommended) |

**Whisper**

| Setting | Description |
|---|---|
| Whisper model | Model to use for local transcription |
| Model list | Download status and one-click download for each available model |

Available Whisper models:

| Model | Size | Notes |
|---|---|---|
| `large-v3-turbo` | ~1.6 GB | High quality, 8x faster than large-v3 — recommended |
| `distil-large-v3` | ~1.5 GB | Fast, near-large quality |
| `large-v3` | ~3 GB | Best accuracy, slow on CPU |
| `medium` | ~1.5 GB | Good balance |
| `small` | ~500 MB | Fast, lower accuracy |

GPU acceleration is used automatically if CUDA libraries are present. Falls back to CPU otherwise.

**Ollama**

| Setting | Description |
|---|---|
| Ollama model | Model name (curated list + free-text for any Ollama model) |
| Pull Model | Download a custom model from Ollama registry |
| Ollama host | Ollama server address (default: `http://localhost:11434`) |
| Model list | Download status and one-click download for each available model |

Available Ollama models (curated):

| Model | Size | Notes |
|---|---|---|
| `phi4-mini` | ~3 GB | Lightest, good quality |
| `gemma3:4b` | ~4 GB | Good quality |
| `qwen2.5:7b` | ~5 GB | Very capable |
| `llama3.1:8b` | ~5 GB | Very capable |
| `gemma3:12b` | ~8 GB | Best quality, high RAM required |

### API Keys tab

Add API keys as environment variable key-value pairs. Pre-populated suggestions for common providers (Gemini, OpenAI, Anthropic, Groq, OpenRouter, ElevenLabs, Deepgram). Keys are passed directly to providers and also set as environment variables.

### Prompts tab

Customize the transcription and summarization prompts. Each has a **Reset to default** button. The `{transcript}` placeholder in the summarization prompt is replaced with the transcript text.

Note: transcription prompts apply to Gemini direct provider only — Whisper, ElevenLabs, and LiteLLM transcription providers do not use custom prompts.

## Workflow

1. Click **Record (Headphones)** or **Record (Speaker)** to start
2. The timer shows elapsed recording time; **Pause** / **Resume** as needed
3. Click **Stop** — a 5-second countdown begins (click **Cancel** to abort)
4. After 5 seconds, transcription starts automatically
5. When done, links to the transcript and notes files appear in the window

## Noise Reduction (Optional)

If your microphone picks up too much ambient noise, enable PipeWire's WebRTC noise suppression:

**Temporary (current session only):**
```bash
pactl load-module module-echo-cancel aec_method=webrtc noise_suppression=true
```

**Permanent:**

Create `~/.config/pipewire/pipewire-pulse.conf.d/echo-cancel.conf`:
```
pulse.cmd = [
  { cmd = "load-module" args = "module-echo-cancel aec_method=webrtc noise_suppression=true" flags = [] }
]
```

Then restart PipeWire:
```bash
systemctl --user restart pipewire pipewire-pulse
```

## Logs

Application logs:
```
~/.local/share/meeting-recorder/meeting-recorder.log
```

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v   # 54 tests
```

## License

MIT
