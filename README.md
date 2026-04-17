<p align="center">
  <img src="src/meeting_recorder/assets/icons/meeting-recorder-logo-animated.svg" alt="Linhaça" width="128" height="128">
</p>

<h1 align="center">Linhaça</h1>

<p align="center">
  Grave. Transcreva. Resuma. — O Granola.ai que roda no Linux.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="Licença: MIT"></a>
  <a href="https://github.com/ianpsa/granola-linux"><img src="https://img.shields.io/badge/fork-ianpsa%2Fgranola--linux-orange" alt="Fork"></a>
</p>

<p align="center">
  App de desktop para Linux que grava reuniões, transcreve localmente com <strong>Whisper</strong><br>
  e resume com o <strong>Claude Code CLI</strong> — sem precisar de chaves de API na nuvem.<br>
  <strong>Arch Linux</strong> &middot; PipeWire + Wayland &middot; GTK3
</p>

> **Linhaça** é um fork do [granola-linux](https://github.com/ianpsa/granola-linux), que por sua vez é fork do [AJV009/meeting-recorder](https://github.com/AJV009/meeting-recorder).
> O [Granola](https://granola.ai) é ótimo — mas só roda no Mac. Linhaça é a versão que realmente importa: roda no Linux, processa localmente e não manda seus áudios pra nuvem de ninguém.

---

## Início Rápido

```bash
# Clone e instale num venv com site-packages do sistema (necessário para GTK)
git clone https://github.com/ianpsa/granola-linux.git
cd granola-linux
python -m venv --system-site-packages .venv
.venv/bin/pip install -e .

# Execute
.venv/bin/python -m meeting_recorder
```

Ou use o script de instalação completo:

```bash
./install.sh
```

Instala dependências via pacman, cria o venv com uv e instala o `gpu-screen-recorder` do AUR (se yay/paru disponível).

---

## Funcionalidades

### Gravação

- **Dois modos** — *Fones* (microfone + áudio do sistema) ou *Alto-falante* (só microfone, evita eco)
- **Pausar / Retomar** durante a gravação
- **Trilhas de áudio separadas** — salva microfone e sistema em arquivos independentes para melhor diarização
- **Transcrever arquivos existentes** — arraste qualquer arquivo de áudio/vídeo para transcrever sem gravar

### Transcrição

| Provedor | Como funciona | Requisito |
|---|---|---|
| **Whisper** | Roda localmente via faster-whisper, acelera com GPU se CUDA disponível | Download do modelo (~500 MB – 3 GB) |
| **Google Gemini** | Áudio enviado para a API multimodal do Gemini | Chave de API |
| **ElevenLabs Scribe v2** | Diarização nativa, até 32 falantes | Chave de API |
| **LiteLLM** | Roteia para Groq, OpenAI, Deepgram e outros | Chave do provedor |

### Sumarização

| Provedor | Como funciona | Requisito |
|---|---|---|
| **Claude Code CLI** | Chama `claude --print` localmente | Assinatura do Claude Code |
| **LiteLLM** | Roteia para Gemini, Ollama, OpenAI, Anthropic, OpenRouter etc. | Chave do provedor (ou Ollama local) |

Combine à vontade — Whisper + Ollama roda 100% offline, sem nenhuma chave de API.

### Gravação de Tela

- Captura Wayland nativa **por monitor** via gpu-screen-recorder
- **Mesclar com áudio** — combina gravação de tela + áudio num único vídeo
- **Inibição de luz noturna** — pausa automaticamente o night light do KDE durante a gravação para cores precisas

### Explorador de Reuniões

- Lista todas as reuniões gravadas com busca
- **Títulos gerados por IA** — nomeia reuniões automaticamente a partir das notas, ou gera manualmente
- **Renomear inline** — duplo clique para renomear qualquer reunião
- Abre pastas, exclui gravações, seleção em massa

### Recursos Inteligentes

- **Detecção de chamadas** — monitora o PipeWire por chamadas ativas e notifica para começar a gravar
- **Título automático** — IA gera um título curto a partir das notas após o processamento
- **Limpeza de artefatos** — escolha quais arquivos de saída manter (áudio, transcrições, gravações de tela, notas)
- **Gerenciamento de memória GPU** — descarrega modelos automaticamente entre etapas para evitar OOM em GPUs limitadas
- **Bandeja do sistema** — StatusNotifierItem no KDE (fallback pystray), ações configuráveis, status de jobs em segundo plano
- **Inicialização automática** — opcionalmente inicia no login

---

## Como Funciona

1. Clique em **Gravar (Fones)** ou **Gravar (Alt-falante)** para iniciar
2. Pause / Retome conforme necessário — um timer mostra o tempo decorrido
3. Clique em **Parar** — transcrição e sumarização rodam automaticamente
4. Veja os resultados no app ou abra a pasta de saída

Cada sessão é salva numa hierarquia por data:

```
~/meetings/
└── 2026/
    └── Março/
        └── 04/
            └── 14-30_Standup/
                ├── recording.mp3              # Áudio combinado
                ├── recording_mic.mp3          # Trilha do microfone (se separadas)
                ├── recording_system.mp3       # Trilha do sistema (se separadas)
                ├── screen-eDP-1.mp4           # Gravação de tela (se ativado)
                ├── screen-eDP-1_merged.mp4    # Tela + áudio mesclados (se ativado)
                ├── transcript.md
                └── notes.md
```

---

## Provedores e Modelos

O LiteLLM roteia via prefixo no nome do modelo:

```
gemini/gemini-2.5-flash              # Google Gemini
ollama/phi4-mini                     # Ollama local
openai/gpt-4o                        # OpenAI
anthropic/claude-sonnet-4-latest     # Anthropic
openrouter/anthropic/claude-sonnet-4 # OpenRouter
groq/whisper-large-v3                # Groq (transcrição)
```

Selecione nas listas em Configurações, ou digite qualquer string `provedor/modelo`.

| Provedor | Requisito |
|---|---|
| **Gemini** | Chave de API em [aistudio.google.com](https://aistudio.google.com) |
| **ElevenLabs** | Chave de API em [elevenlabs.io](https://elevenlabs.io) |
| **Whisper** | Modelo baixado em Configurações → Config. de Modelos |
| **Ollama** | [Ollama](https://ollama.com) instalado e rodando |
| **Claude Code** | [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code/overview) instalado e no PATH |
| **Outros provedores LiteLLM** | Chave configurada em Configurações → Chaves de API |

---

## Instalação

### A partir do Fonte

```bash
git clone https://github.com/ianpsa/granola-linux.git
cd granola-linux
./install.sh
```

Instala dependências via pacman, configura um venv Python via uv e instala o gpu-screen-recorder do AUR se yay/paru estiver disponível.

### Desenvolvimento

```bash
git clone https://github.com/ianpsa/granola-linux.git
cd granola-linux
python3 -m venv .venv --system-site-packages
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m meeting_recorder
```

### Desinstalar

```bash
./uninstall.sh
```

> Suas gravações (`~/meetings/`) e configurações (`~/.config/meeting-recorder/`) são preservadas.

### Requisitos

- Arch Linux com PipeWire (testado no KDE Plasma 6 / Wayland)
- `ffmpeg`, `pipewire`, `pipewire-pulse`, `wireplumber`, Python 3, GTK3
- Opcional: `gpu-screen-recorder` (AUR) para gravação de tela

---

## Configurações

Abra **Configurações** pelo ícone de engrenagem ou menu da bandeja. As configurações estão organizadas em abas:

| Aba | O que controla |
|---|---|
| **Geral** | Provedores de transcrição/sumarização, modelo LiteLLM, pasta de saída, qualidade, timeout, inicialização automática, detecção de chamadas, título automático |
| **Plataforma** | Trilhas de áudio separadas, gravação de tela (monitores, FPS, mesclar), inibição de luz noturna |
| **Config. de Modelos** | Modelo Gemini, download do modelo Whisper, modelo + host + pull do Ollama |
| **Chaves de API** | Chaves de API dos provedores (Gemini, OpenAI, Anthropic, Groq, OpenRouter, ElevenLabs, Deepgram) |
| **Prompts** | Prompts customizados de transcrição e sumarização com reset ao padrão |
| **Artefatos** | Escolha quais arquivos de saída manter após o processamento |
| **Bandeja** | Ação padrão ao clicar na bandeja quando ocioso e quando gravando |

<details>
<summary><strong>Modelos Whisper</strong></summary>

| Modelo | Tamanho | Notas |
|---|---|---|
| `large-v3-turbo` | ~1,6 GB | Alta qualidade, 8x mais rápido que large-v3 — recomendado |
| `distil-large-v3` | ~1,5 GB | Rápido, qualidade próxima ao large |
| `large-v3` | ~3 GB | Melhor precisão, lento na CPU |
| `medium` | ~1,5 GB | Bom equilíbrio |
| `small` | ~500 MB | Rápido, menor precisão |

Aceleração por GPU é automática se CUDA estiver disponível.

</details>

<details>
<summary><strong>Modelos Ollama (curados)</strong></summary>

| Modelo | Tamanho | Notas |
|---|---|---|
| `phi4-mini` | ~3 GB | Mais leve, boa qualidade |
| `gemma3:4b` | ~4 GB | Boa qualidade |
| `qwen2.5:7b` | ~5 GB | Muito capaz |
| `llama3.1:8b` | ~5 GB | Muito capaz |
| `gemma3:12b` | ~8 GB | Melhor qualidade, precisa de mais RAM |

</details>

<details>
<summary><strong>Personalização de prompts</strong></summary>

Edite os prompts de transcrição e sumarização em Configurações → Prompts. Cada um tem um botão **Restaurar padrão**. O placeholder `{transcript}` no prompt de sumarização é substituído pelo texto da transcrição.

Nota: prompts de transcrição se aplicam apenas ao provedor Gemini direto — Whisper, ElevenLabs e LiteLLM não usam prompts customizados.

</details>

---

## Dicas e Solução de Problemas

<details>
<summary><strong>Redução de ruído</strong></summary>

Ative a supressão de ruído WebRTC do PipeWire:

**Temporário (sessão atual):**
```bash
pactl load-module module-echo-cancel aec_method=webrtc noise_suppression=true
```

**Permanente** — crie `~/.config/pipewire/pipewire-pulse.conf.d/echo-cancel.conf`:
```
pulse.cmd = [
  { cmd = "load-module" args = "module-echo-cancel aec_method=webrtc noise_suppression=true" flags = [] }
]
```

Depois reinicie o PipeWire:
```bash
systemctl --user restart pipewire pipewire-pulse
```

</details>

<details>
<summary><strong>Logs</strong></summary>

```
~/.local/share/meeting-recorder/meeting-recorder.log
```

</details>

<details>
<summary><strong>Recuperar gravações de tela corrompidas</strong></summary>

Se uma gravação de tela estiver sem o moov atom (ex.: por crash), veja o guia completo em [docs/recuperar-gravacoes-corrompidas.md](docs/recuperar-gravacoes-corrompidas.md).

</details>

---

## Testes

```bash
python -m pytest tests/ -v
```

---

## Licença

MIT
