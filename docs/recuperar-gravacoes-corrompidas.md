# Recuperar Gravações de Tela Corrompidas (moov atom ausente)

Quando o `gpu-screen-recorder` é encerrado sem um shutdown limpo (ex.: SIGKILL, crash do processo, ou o bug de deadlock no pipe stderr corrigido no commit 7bde9a3), os arquivos MP4 resultantes ficam sem o atom `moov` — o índice que diz aos players como ler o arquivo. Os dados brutos de vídeo no atom `mdat` estão intactos, mas o arquivo é inreproduível.

## Sintomas

- Player de vídeo mostra "arquivo corrompido" ou recusa abrir
- `ffprobe` reporta: `moov atom not found`
- O arquivo tem tamanho razoável (não é 0 bytes)

## Pré-requisitos

- `ffmpeg` e `ffprobe` instalados
- `gpu-screen-recorder` instalado (para criar um arquivo de referência)
- `python3`
- Acesso ao mesmo setup de monitor usado durante a gravação original

## Passos para Recuperação

### 1. Verificar se o arquivo é recuperável

```bash
ffprobe screen-HDMI-A-1.mp4
# Deve mostrar: "moov atom not found" — confirma que os dados estão lá mas o índice está ausente

# Verificar se o arquivo tem dados reais (atoms ftyp + mdat)
xxd screen-HDMI-A-1.mp4 | head -5
# Deve mostrar: "ftyp" perto do início e "mdat" logo depois
```

### 2. Criar uma gravação de referência

Grave um clipe curto (2-3 segundos) no **mesmo monitor** usando as mesmas configurações do `gpu-screen-recorder`. Isso fornece os cabeçalhos de codec SPS/PPS necessários para decodificar o stream H.264.

```bash
gpu-screen-recorder -w HDMI-A-1 -f 30 -fallback-cpu-encoding yes -o /tmp/ref_HDMI-A-1.mp4 &
REF_PID=$!
sleep 3
kill -SIGINT $REF_PID
wait $REF_PID 2>/dev/null

# Verificar se a referência é válida
ffprobe -v error -show_entries stream=width,height -show_entries format=duration \
  -of default=noprint_wrappers=1 /tmp/ref_HDMI-A-1.mp4
```

Repita para cada monitor se estiver recuperando múltiplos arquivos (ex.: `eDP-1`, `DP-1`).

### 3. Extrair SPS/PPS e stream H.264 bruto, depois remuxar

Execute este script Python. Ele:
1. Extrai SPS (Sequence Parameter Set) e PPS (Picture Parameter Set) do box `avcC` do MP4 de referência
2. Converte o `mdat` do arquivo corrompido de formato AVCC (NAL units com prefixo de comprimento 4 bytes) para formato Annex B (prefixo com start code)
3. Reinjecta SPS/PPS antes de cada keyframe para que o decoder possa ressincronizar
4. Usa ffmpeg para remuxar o stream H.264 bruto num MP4 válido

```python
#!/usr/bin/env python3
"""Recupera um MP4 de gravação de tela com o moov atom ausente."""
import struct
import os
import subprocess
import sys

def extract_sps_pps(ref_path):
    """Extrai NAL units SPS e PPS do box avcC de um MP4 funcional."""
    with open(ref_path, 'rb') as f:
        data = f.read()
    avcc_pos = data.find(b'avcC')
    if avcc_pos < 0:
        raise ValueError("Nenhum avcC encontrado no arquivo de referência")
    pos = avcc_pos + 4 + 5  # pula tag + version/profile/compat/level/lengthSize
    sps_count = data[pos] & 0x1f
    pos += 1
    sps_list = []
    for _ in range(sps_count):
        sps_len = struct.unpack('>H', data[pos:pos+2])[0]
        pos += 2
        sps_list.append(data[pos:pos+sps_len])
        pos += sps_len
    pps_count = data[pos]
    pos += 1
    pps_list = []
    for _ in range(pps_count):
        pps_len = struct.unpack('>H', data[pos:pos+2])[0]
        pos += 2
        pps_list.append(data[pos:pos+pps_len])
        pos += pps_len
    return sps_list, pps_list

def recover(src, dst, ref_path, framerate=30):
    """Recupera um MP4 corrompido usando os cabeçalhos de codec de um arquivo de referência."""
    sps_list, pps_list = extract_sps_pps(ref_path)

    with open(src, 'rb') as f:
        data = f.read()

    mdat_pos = data.find(b'mdat')
    if mdat_pos < 0:
        print(f"ERRO: nenhum atom mdat encontrado em {src}")
        return False

    # Converte NAL units AVCC (prefixo de comprimento) para Annex B (prefixo start code)
    h264_path = dst + '.h264'
    with open(h264_path, 'wb') as out:
        # Escreve SPS/PPS iniciais
        for sps in sps_list:
            out.write(b'\x00\x00\x00\x01')
            out.write(sps)
        for pps in pps_list:
            out.write(b'\x00\x00\x00\x01')
            out.write(pps)

        pos = mdat_pos + 4  # pula a tag 'mdat'
        count = 0
        while pos < len(data) - 4:
            nal_len = struct.unpack('>I', data[pos:pos+4])[0]
            if nal_len == 0 or nal_len > 10_000_000 or pos + 4 + nal_len > len(data):
                break
            pos += 4
            nal_type = data[pos] & 0x1f

            # Reinjecta SPS/PPS antes de cada keyframe IDR
            if nal_type == 5:
                for sps in sps_list:
                    out.write(b'\x00\x00\x00\x01')
                    out.write(sps)
                for pps in pps_list:
                    out.write(b'\x00\x00\x00\x01')
                    out.write(pps)

            out.write(b'\x00\x00\x00\x01')
            out.write(data[pos:pos+nal_len])
            count += 1
            pos += nal_len

    print(f"Extraídas {count} NAL units, remuxando...")

    # Remuxar stream H.264 bruto num container MP4 válido
    result = subprocess.run(
        ['ffmpeg', '-y', '-fflags', '+genpts', '-r', str(framerate),
         '-f', 'h264', '-i', h264_path,
         '-c', 'copy', '-r', str(framerate),
         '-movflags', '+faststart', dst],
        capture_output=True, text=True
    )
    os.unlink(h264_path)

    if result.returncode == 0 and os.path.exists(dst):
        probe = subprocess.run(
            ['ffprobe', '-v', 'error',
             '-show_entries', 'stream=width,height,duration,nb_frames',
             '-of', 'default=noprint_wrappers=1', dst],
            capture_output=True, text=True)
        print(f"Recuperado: {dst}")
        print(probe.stdout.strip())
        return True
    else:
        print(f"FALHOU: {result.stderr[-300:]}")
        return False

if __name__ == '__main__':
    if len(sys.argv) < 4:
        print(f"Uso: {sys.argv[0]} <referencia.mp4> <corrompido.mp4> <saida.mp4> [framerate]")
        print(f"  referencia.mp4  - Uma gravação curta funcional do mesmo monitor/configurações")
        print(f"  corrompido.mp4  - O arquivo quebrado com moov atom ausente")
        print(f"  saida.mp4       - Onde escrever o arquivo recuperado")
        print(f"  framerate       - FPS da gravação (padrão: 30)")
        sys.exit(1)

    fps = int(sys.argv[4]) if len(sys.argv) > 4 else 30
    recover(sys.argv[2], sys.argv[3], sys.argv[1], fps)
```

### 4. Executar a recuperação

```bash
# Salve o script acima como recover_mp4.py, depois:
python3 recover_mp4.py /tmp/ref_HDMI-A-1.mp4 screen-HDMI-A-1.mp4 screen-HDMI-A-1_recuperado.mp4
```

### 5. Verificar o arquivo recuperado

```bash
ffprobe -v error \
  -show_entries stream=width,height,duration,nb_frames,codec_name \
  -of default=noprint_wrappers=1 screen-HDMI-A-1_recuperado.mp4

# Tentar reproduzir
mpv screen-HDMI-A-1_recuperado.mp4
# ou
vlc screen-HDMI-A-1_recuperado.mp4
```

## Como Funciona

Arquivos MP4 têm dois atoms críticos:
- **`mdat`** — os dados reais de vídeo/áudio (NAL units H.264)
- **`moov`** — o índice/metadados (config de codec, tamanhos de frames, timestamps, SPS/PPS)

Quando o gpu-screen-recorder é encerrado de forma suja, o `moov` nunca é escrito (ele é escrito no final durante a finalização). O processo de recuperação:

1. **Extração de SPS/PPS**: O H.264 Sequence Parameter Set e Picture Parameter Set contêm a configuração do codec (resolução, perfil, nível). Em arquivos MP4 eles ficam no box `avcC` do atom `moov`, não inline no stream. Extraímos de uma gravação de referência feita com configurações idênticas.

2. **Conversão AVCC → Annex B**: MP4 armazena NAL units H.264 com prefixos de comprimento de 4 bytes (formato AVCC). Streams H.264 brutos usam start codes (`00 00 00 01`) em vez disso (formato Annex B). O script converte entre esses formatos.

3. **Injeção de SPS/PPS**: SPS/PPS são injetados antes de cada IDR (keyframe) no stream para que o decoder possa inicializar em qualquer keyframe, não só no início.

4. **Remux com ffmpeg**: O stream Annex B bruto é passado ao ffmpeg, que gera timestamps adequados (`-fflags +genpts`) no framerate especificado e escreve um MP4 válido com um atom `moov` completo.

## Limitações

- A gravação de referência **deve** usar as mesmas configurações do `gpu-screen-recorder` (resolução, framerate, codec, qualidade) que o arquivo corrompido
- Trilhas de áudio não são recuperadas (gravações de tela do gpu-screen-recorder são somente vídeo)
- Timestamps de frames são reconstruídos assumindo framerate constante — pequeno drift de timing é possível
- Se o arquivo corrompido também foi afetado pelo bug de deadlock no pipe stderr, o vídeo pode cobrir menos tempo de relógio do que a duração real da reunião
