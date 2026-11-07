# Editor de PDF (Windows 10/11)

Editor de PDF **100% offline** (sem telemetria, nada é enviado à internet), em português do Brasil.

## Como usar o programa
Dê dois cliques em **EditorDePDF.exe** (não precisa instalar Python nem nada). Para abrir um PDF: botão **Abrir**, arrastar o arquivo para a janela, ou "Abrir com…" no Windows.

## Como obter o .exe (importante: leia)
O .exe **não vem pronto neste pacote**, pois foi escrito num ambiente Linux, que não gera programas do Windows. Escolha um caminho:

### Caminho A — no seu Windows (build.bat)
1. Instale o Python 3.11 ou 3.12 (python.org) marcando **Add python.exe to PATH**.
2. Dê dois cliques em **build.bat**. Ele instala as dependências, roda os testes, gera e testa o .exe.
3. O resultado fica em `dist\EditorDePDF.exe`. Esse arquivo roda em qualquer Windows, sem instalar nada.

### Caminho B — pelo GitHub (sem instalar nada no seu PC)
1. Crie uma conta em github.com e clique em **New repository** (nome: `editor-de-pdf`, pode ser privado).
2. Na página do repositório, clique em **uploading an existing file** e arraste TODO o conteúdo desta pasta
   (incluindo a pasta oculta `.github`; se não conseguir arrastar pastas ocultas, use o GitHub Desktop ou o Git).
3. Clique em **Commit changes**.
4. Abra a aba **Actions**. O trabalho "Gerar EditorDePDF.exe" começa sozinho (ou clique em **Run workflow**).
5. Espere uns 5–10 minutos até aparecer um ✔ verde. Clique no trabalho e, em **Artifacts**, baixe **EditorDePDF-windows**.
6. Descompacte o .zip: dentro está o `EditorDePDF.exe`.
Se aparecer ✖ vermelho, abra o passo que falhou e envie a mensagem para o desenvolvedor.

## Recursos
Abrir (senha, arrastar e soltar) · zoom (Ctrl+roda, largura, página) · rolagem contínua · miniaturas · ir para página (Ctrl+G) ·
reordenar (arrastar miniaturas), girar, excluir, duplicar, inserir em branco, extrair · juntar e dividir (intervalos, a cada N, uma por página) ·
texto (fonte, tamanho, cor, negrito/itálico; mover/redimensionar/apagar) · imagens e assinatura (desenhar/importar/salvar) ·
marca-texto, sublinhar, riscar, desenho livre, retângulo, círculo, seta, nota · formulários (preencher e achatar) ·
tarja preta que remove o conteúdo de verdade · marca d'água e numeração · comprimir (leve/médio/forte) ·
proteger/remover senha · imagens ⇄ PDF · desfazer/refazer (Ctrl+Z/Ctrl+Y) · tema claro/escuro · aviso de alterações não salvas.

## Limitações conhecidas
- **Editar texto existente** é "cobrir e escrever por cima": o texto original continua no arquivo, a menos que você marque *remover de verdade*. Fonte, espaçamento e alinhamento do novo texto podem diferir do original.
- **Tarja (redação)**: cada página tarjada vira **imagem** (200 DPI); o texto dela deixa de ser selecionável/pesquisável. Marcadores, links e campos de formulário do documento são descartados nesse processo (por segurança).
- Texto adicionado usa fontes padrão do PDF (Helvetica, Times, Courier), com acentos do português; caracteres fora do Latin-1 (ex.: emojis) viram "?".
- Marca-texto/sublinhado/riscado são desenhados por arrasto (não "grudam" no texto automaticamente).
- Ao realizar operações de páginas (girar, excluir, marca d'água…), os itens pendentes (texto, imagens, anotações) são "fixados" no PDF; ainda dá para desfazer com Ctrl+Z.
- Comprimir só recomprime imagens simples (sem máscara de transparência); PDFs sem imagens grandes quase não diminuem.
- Juntar PDFs não preserva campos de formulário/marcadores dos arquivos de origem.
- Salvar um PDF que veio com senha o grava com a mesma senha (use "Remover senha" antes para tirá-la).
- **OCR (Tesseract) não está incluído**: o recurso está desativado nesta versão.
- PDFs de 200+ páginas funcionam (só as páginas visíveis são renderizadas), mas operações que reconstroem o arquivo (tarja, marca d'água, compressão) levam mais tempo.

## Testes automáticos
`python -m unittest discover -s tests -v` (testa juntar, dividir, girar, senha, redação, anotações, formulários, compressão, conversões e desfazer/refazer).
O próprio .exe tem `EditorDePDF.exe --autoteste`, que abre a interface sem tela e confere abrir/renderizar/editar/salvar.

## Estrutura
`editor_pdf/core` = motor de PDF (sem interface, testado) · `editor_pdf/ui` = interface PySide6 · `tests` · `build.bat` · `.github/workflows/build.yml`
