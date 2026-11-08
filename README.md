# GCode Tools

Software desktop **tipo G-Code Ripper** para manipulação avançada de arquivos G-Code CNC.
Desenvolvido em **Python + PySide6 (Qt6)** com visualizador 3D acelerado por hardware (**PyVista / VTK via GPU/OpenGL**).

---

## Funcionalidades

| # | Funcionalidade | Descrição |
|---|---|---|
| 1 | 📊 Estatísticas & Simulação | Estimativa de tempo de usinagem, distâncias de corte/rápido, playback animado com fresa 3D |
| 2 | 🗺️ Surface Mapping | Auto-limita X e Y aos limites do G-Code, edição/exclusão de pontos medidos e do padrão de varredura, interpolação Z e gerador Mach3/GRBL com padrões Raster, Serpentina e Circular (anéis concêntricos) |
| 3 | 🔄 4º Eixo | Converte G-Code plano XY para eixo rotativo A com compensação de Z no centro/superfície |
| 4 | ↔️ Transformações | Escala, translação, espelhamento e rotação do G-Code |
| 5 | ✂️ Dividir | Divide arquivos por linhas, troca de ferramenta (M6) ou camada Z |
| 6 | 〰️ Converter Arcos | G2/G3 → G1 com tolerância configurável (inclui círculos completos 360°) |
| 7 | 📝 Editor G-Code | Editor com realce de sintaxe colorido (G/M/XYZ/FS), busca e sincronização 3D |
| 8 | 👁️ Visualizador 3D & Exportação | Órbita 3D, point picking de probe, exportação de percursos/malhas para STL, PLY, VTK, OBJ |

---

## Requisitos

- Python 3.10+
- Dependências (instalar via pip):

```bash
pip install -r requirements.txt
```

---

## Como Executar

```bash
python main.py
```

### Testes

O núcleo (`core/`) possui testes de regressão com `unittest` (não requer dependências extras):

```bash
python -m unittest discover -s tests -v
```

---

## Gerar Executável (Windows)

Pré-requisito: Windows 64-bit com Python 3.10+ instalado.

**Opção rápida (duplo clique):** execute `build_exe.bat`. Ele instala as
dependências, o PyInstaller e gera o executável automaticamente.

**Ou manualmente:**

```bash
pip install -r requirements.txt
pip install -r requirements-build.txt
pyinstaller --noconfirm --clean GCodeTools.spec
```

O resultado fica em:

```
dist\GCodeTools\GCodeTools.exe
```

> ⚠️ Distribua a pasta `dist\GCodeTools` **inteira** (modo onedir), pois ela
> contém as DLLs do Qt/PySide6 e do VTK/PyVista. O `.exe` sozinho não funciona.
>
> O executável é gerado para a mesma plataforma do build (Windows 64-bit).
> O tamanho final fica em torno de **1 GB**, devido às bibliotecas do Qt e do VTK.
>
> Na primeira execução o Windows SmartScreen pode exibir um aviso por o
> executável não ter assinatura digital; use "Mais informações → Executar assim mesmo".

---

## Estrutura do Projeto

```
gcode-tools/
├── main.py                  # Ponto de entrada da aplicação
├── requirements.txt         # Dependências do projeto
│
├── core/                    # Lógica de negócio (sem dependência de GUI)
│   ├── gcode_parser.py      # Parser e writer de G-Code (reconstrução fiel de blocos)
│   ├── surface_map.py       # Interpolação de relevo e auto-leveling Z
│   ├── rotary_wrap.py       # Conversor plano XY → 4º eixo A (cilindro)
│   ├── transforms.py        # Escala, translação, rotação, espelho
│   ├── splitter.py          # Divisão de arquivos em partes
│   ├── arc_converter.py     # Linearização de arcos circulares (G2/G3 → G1)
│   └── statistics.py        # Análise métrica, tempos e pontos de simulação
│
├── tests/                   # Bateria completa de testes automatizados
│   └── test_core.py         # Testes de regressão do núcleo
│
└── gui/                     # Interface gráfica desktop em PySide6
    ├── app.py               # Janela principal com drag-and-drop e QSettings
    ├── tabs/                # Uma aba modular por funcionalidade
    │   ├── tab_info.py      # Estatísticas, métricas e player de simulação 3D
    │   ├── tab_surface.py   # Probing, tabela e edição de alturas
    │   ├── tab_rotary.py    # Parâmetros e visualização de 4º eixo
    │   ├── tab_transform.py # Transformações geométricas
    │   ├── tab_splitter.py  # Divisor de arquivos
    │   ├── tab_arcs.py      # Conversor de arcos
    │   └── tab_editor.py    # Editor com syntax highlighting e sincronização
    └── widgets/
        └── pyvista_viewer.py # Visualizador 3D GPU com picking e visibilidade rápida
```

---

## Novidades na Versão 2.0.0

- **🎮 Simulação 3D Interativa:** Acompanhe a ferramenta de corte percorrendo as trajetórias da peça em tempo real com controle de velocidade (1x até 100x), slider de progresso e botões Play/Pause/Reset.
- **📝 Editor de Código Embutido:** Edite comandos G-Code diretamente na aplicação com realce de sintaxe em tempo real para comandos G, M, eixos, avanço, rotação e comentários.
- **📤 Exportação de Malha 3D:** Exporte peças e relevos compensados diretamente em formatos 3D padrão como `.stl`, `.ply`, `.vtk` e `.obj`.
- **📂 Arrastar e Soltar (Drag & Drop):** Abra qualquer arquivo de G-Code simplesmente arrastando-o para dentro da janela do software.
- **⚡ Alta Performance 3D:** Alternância instantânea de camadas (G1, G0, Grade, Caixa, Cilindro) via controle de visibilidade de atores VTK sem recriar a cena.
- **💾 Persistência de Preferências:** Guarda automaticamente o último diretório utilizado e as dimensões da janela entre sessões.

---

## Formato de Arquivos de Pontos (Probing)

O software aceita os arquivos de saída de probing gerados por:
- **Mach3** (arquivo de log gerado via `M40` / `M41`, normalmente `points.txt` salvo com coordenadas X Y Z)
- **G-Code Ripper** (arquivos de dados de probing `.txt`, `.dat` ou `.csv`)
- **GRBL / Candle / OpenBuilds / bCNC**

Exemplos de formatos aceitos automaticamente:
```
-149.058 -91.896 0.024
-106.234 -91.896 0.035
```
ou delimitado por vírgula:
```csv
X,Y,Z
-149.058,-91.896,0.024
-106.234,-91.896,0.035
```

---

## Licença

Projeto open-source. Use, modifique e distribua livremente.
