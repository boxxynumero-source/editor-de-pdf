"""Operações sobre PDFs (todas trabalham com `bytes` e devolvem `bytes`)."""
from __future__ import annotations

import io
import os
import re

import pikepdf
from pikepdf import Name, Pdf


class PdfError(Exception):
    pass


class SenhaNecessaria(PdfError):
    pass


class SenhaIncorreta(PdfError):
    pass


# --------------------------------------------------------------------------
# Abrir / salvar
# --------------------------------------------------------------------------
def ler_arquivo(caminho: str) -> bytes:
    try:
        with open(caminho, "rb") as f:
            return f.read()
    except PermissionError as e:
        raise PdfError("Não foi possível ler o arquivo: ele pode estar em uso por outro programa ou sem permissão de acesso.") from e
    except FileNotFoundError as e:
        raise PdfError("Arquivo não encontrado.") from e
    except OSError as e:
        raise PdfError(f"Erro ao ler o arquivo: {e}") from e


def abrir(dados: bytes, senha: str = "") -> Pdf:
    try:
        return Pdf.open(io.BytesIO(dados), password=senha)
    except pikepdf.PasswordError as e:
        if senha:
            raise SenhaIncorreta("Senha incorreta.") from e
        raise SenhaNecessaria("Este PDF é protegido por senha.") from e
    except pikepdf.PdfError as e:
        raise PdfError(f"O arquivo está corrompido ou não é um PDF válido.\n({e})") from e


def _salvar(pdf: Pdf, **kw) -> bytes:
    b = io.BytesIO()
    kw.setdefault("compress_streams", True)
    kw.setdefault("object_stream_mode", pikepdf.ObjectStreamMode.generate)
    pdf.save(b, **kw)
    return b.getvalue()


def normalizar(dados: bytes, senha: str = "") -> bytes:
    """Abre (com senha, se preciso) e devolve uma cópia SEM criptografia."""
    with abrir(dados, senha) as pdf:
        if len(pdf.pages) == 0:
            raise PdfError("O PDF não tem páginas.")
        return _salvar(pdf, encryption=False)


def num_paginas(dados: bytes) -> int:
    with abrir(dados) as pdf:
        return len(pdf.pages)


def escrever_atomico(caminho: str, dados: bytes):
    tmp = caminho + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(dados)
        os.replace(tmp, caminho)
    except PermissionError as e:
        raise PdfError("Não foi possível gravar: o arquivo está em uso por outro programa ou a pasta não permite gravação.") from e
    except OSError as e:
        raise PdfError(f"Erro ao gravar o arquivo: {e}") from e
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# --------------------------------------------------------------------------
# Intervalos de páginas ("1-3, 5, 8-")
# --------------------------------------------------------------------------
def _parte(txt: str, total: int) -> list[int]:
    txt = txt.strip()
    m = re.fullmatch(r"(\d*)\s*-\s*(\d*)", txt)
    if m:
        a = int(m.group(1)) if m.group(1) else 1
        b = int(m.group(2)) if m.group(2) else total
    elif txt.isdigit():
        a = b = int(txt)
    else:
        raise ValueError(f"Intervalo inválido: “{txt}”. Use o formato 1-3, 5, 8-")
    if a < 1 or b > total or a > b:
        raise ValueError(f"Intervalo “{txt}” fora do documento (1 a {total}).")
    return list(range(a - 1, b))


def parse_partes(texto: str, total: int) -> list[list[int]]:
    texto = (texto or "").strip()
    if not texto:
        return [list(range(total))]
    return [_parte(p, total) for p in texto.split(",") if p.strip()]


def parse_paginas(texto: str, total: int) -> list[int]:
    vistos, out = set(), []
    for parte in parse_partes(texto, total):
        for i in parte:
            if i not in vistos:
                vistos.add(i)
                out.append(i)
    return sorted(out)


# --------------------------------------------------------------------------
# Organizar páginas
# --------------------------------------------------------------------------
def reordenar(dados: bytes, ordem: list[int]) -> bytes:
    with abrir(dados) as pdf:
        n = len(pdf.pages)
        if sorted(ordem) != list(range(n)):
            raise PdfError("Ordem de páginas inválida.")
        paginas = [pdf.pages[i] for i in ordem]
        del pdf.pages[:]
        for p in paginas:
            pdf.pages.append(p)
        return _salvar(pdf)


def girar(dados: bytes, indices, graus: int = 90) -> bytes:
    with abrir(dados) as pdf:
        for i in indices:
            pdf.pages[i].rotate(graus, relative=True)
        return _salvar(pdf)


def excluir(dados: bytes, indices) -> bytes:
    with abrir(dados) as pdf:
        indices = sorted(set(indices), reverse=True)
        if len(indices) >= len(pdf.pages):
            raise PdfError("Não é possível excluir todas as páginas do documento.")
        for i in indices:
            del pdf.pages[i]
        return _salvar(pdf)


def duplicar(dados: bytes, indices) -> bytes:
    with abrir(dados) as pdf:
        for i in sorted(set(indices), reverse=True):
            pdf.pages.insert(i + 1, pdf.pages[i])
        return _salvar(pdf)


def inserir_em_branco(dados: bytes, posicao: int, quantidade: int = 1) -> bytes:
    with abrir(dados) as pdf:
        ref = pdf.pages[min(max(posicao - 1, 0), len(pdf.pages) - 1)]
        mb = [float(v) for v in ref.mediabox]
        rot = int(ref.get("/Rotate", 0))
        for k in range(quantidade):
            pg = pikepdf.Page(pikepdf.Dictionary(
                Type=Name.Page, MediaBox=mb, Resources=pikepdf.Dictionary(),
                Contents=pdf.make_stream(b""),
            ))
            if rot:
                pg.obj.Rotate = rot
            pdf.pages.insert(posicao + k, pg)
        return _salvar(pdf)


def extrair(dados: bytes, indices) -> bytes:
    with abrir(dados) as pdf:
        novo = Pdf.new()
        for i in sorted(set(indices)):
            novo.pages.append(pdf.pages[i])
        return _salvar(novo)


# --------------------------------------------------------------------------
# Juntar e dividir
# --------------------------------------------------------------------------
def juntar(arquivos: list[tuple[bytes, str]], progresso=None) -> bytes:
    """arquivos: [(dados, senha), ...] na ordem desejada."""
    novo = Pdf.new()
    abertos = []
    try:
        for n, (dados, senha) in enumerate(arquivos):
            src = abrir(dados, senha)
            abertos.append(src)
            novo.pages.extend(src.pages)
            if progresso:
                progresso(n + 1, len(arquivos))
        return _salvar(novo)
    finally:
        for s in abertos:
            s.close()


def dividir(dados: bytes, modo: str, valor=None, progresso=None) -> list[tuple[str, bytes]]:
    """modo: 'intervalos' (valor='1-3,5'), 'cada_n' (valor=N) ou 'uma_por_pagina'.
    Devolve [(sufixo_do_nome, bytes)]."""
    with abrir(dados) as pdf:
        total = len(pdf.pages)
        if modo == "intervalos":
            grupos = parse_partes(str(valor), total)
        elif modo == "cada_n":
            n = int(valor)
            if n < 1:
                raise ValueError("N deve ser maior que zero.")
            grupos = [list(range(i, min(i + n, total))) for i in range(0, total, n)]
        elif modo == "uma_por_pagina":
            grupos = [[i] for i in range(total)]
        else:
            raise ValueError("Modo de divisão desconhecido.")
        casas = len(str(total))
        saida = []
        for k, g in enumerate(grupos):
            novo = Pdf.new()
            for i in g:
                novo.pages.append(pdf.pages[i])
            nome = f"paginas_{g[0] + 1:0{casas}d}" if len(g) == 1 else f"paginas_{g[0] + 1:0{casas}d}-{g[-1] + 1:0{casas}d}"
            saida.append((nome, _salvar(novo)))
            if progresso:
                progresso(k + 1, len(grupos))
        return saida


# --------------------------------------------------------------------------
# Compressão
# --------------------------------------------------------------------------
NIVEIS_COMPRESSAO = {"leve": None, "medio": (1800, 70), "forte": (1100, 50)}


def _recomprimir_imagem(img, max_lado, qualidade):
    from PIL import Image

    if "/SMask" in img or "/Mask" in img or img.get("/ImageMask", False):
        return
    if int(img.get("/BitsPerComponent", 8)) == 1:
        return
    w, h = int(img.Width), int(img.Height)
    if w * h < 40000:
        return
    original = len(img.read_raw_bytes())
    pil = pikepdf.PdfImage(img).as_pil_image()
    if pil.mode not in ("RGB", "L"):
        pil = pil.convert("RGB")
    if max(pil.size) > max_lado:
        r = max_lado / max(pil.size)
        pil = pil.resize((max(1, int(pil.width * r)), max(1, int(pil.height * r))), Image.LANCZOS)
    b = io.BytesIO()
    pil.save(b, "JPEG", quality=qualidade, optimize=True)
    novo = b.getvalue()
    if len(novo) >= original:
        return
    img.write(novo, filter=Name.DCTDecode)
    img.Width, img.Height = pil.size
    img.ColorSpace = Name.DeviceRGB if pil.mode == "RGB" else Name.DeviceGray
    img.BitsPerComponent = 8
    for chave in ("/Decode", "/DecodeParms"):
        if chave in img:
            del img[chave]


def comprimir(dados: bytes, nivel: str = "medio", progresso=None) -> bytes:
    if nivel not in NIVEIS_COMPRESSAO:
        raise ValueError("Nível de compressão desconhecido.")
    with abrir(dados) as pdf:
        cfg = NIVEIS_COMPRESSAO[nivel]
        if cfg:
            vistos = set()
            n = len(pdf.pages)
            for k, page in enumerate(pdf.pages):
                try:
                    imgs = list(page.get_images().values())
                except AttributeError:  # pikepdf antigo
                    imgs = list(page.images.values())
                for img in imgs:
                    if img.objgen in vistos:
                        continue
                    vistos.add(img.objgen)
                    try:
                        _recomprimir_imagem(img, *cfg)
                    except Exception:
                        continue  # imagem exótica: mantém como está
                if progresso:
                    progresso(k + 1, n)
        pdf.remove_unreferenced_resources()
        out = _salvar(pdf, recompress_flate=True)
    return out if len(out) < len(dados) else dados


# --------------------------------------------------------------------------
# Senhas
# --------------------------------------------------------------------------
def proteger(dados: bytes, senha_abrir: str = "", senha_editar: str = "",
             permitir_imprimir: bool = True, permitir_copiar: bool = True,
             permitir_editar: bool = True) -> bytes:
    if not senha_abrir and not senha_editar:
        raise ValueError("Informe ao menos uma senha (para abrir e/ou para editar).")
    owner = senha_editar or senha_abrir
    perm = pikepdf.Permissions(
        accessibility=True,
        extract=permitir_copiar,
        modify_annotation=permitir_editar,
        modify_assembly=permitir_editar,
        modify_form=permitir_editar,
        modify_other=permitir_editar,
        print_lowres=permitir_imprimir,
        print_highres=permitir_imprimir,
    )
    with abrir(dados) as pdf:
        return _salvar(pdf, encryption=pikepdf.Encryption(user=senha_abrir, owner=owner, R=6, allow=perm))


# --------------------------------------------------------------------------
# Formulários
# --------------------------------------------------------------------------
def listar_campos(dados: bytes) -> list[dict]:
    from pypdf import PdfReader

    campos = PdfReader(io.BytesIO(dados)).get_fields() or {}
    out = []
    for nome, c in campos.items():
        ft = str(c.get("/FT", ""))
        ff = int(c.get("/Ff", 0) or 0)
        valor = c.get("/V", "")
        if ft == "/Tx":
            tipo = "texto"
        elif ft == "/Btn":
            if ff & 65536:
                continue  # botão de ação
            tipo = "radio" if ff & 32768 else "caixa"
        elif ft == "/Ch":
            tipo = "lista"
        else:
            continue
        opcoes = [str(o[1] if isinstance(o, (list, tuple)) and len(o) > 1 else o) for o in (c.get("/Opt") or [])]
        if tipo in ("caixa", "radio"):
            opcoes = [s for s in (c.get("/_States_") or []) if str(s) != "/Off"]
        out.append({"nome": nome, "tipo": tipo, "valor": "" if valor is None else str(valor), "opcoes": [str(o) for o in opcoes]})
    return out


def preencher_campos(dados: bytes, valores: dict) -> bytes:
    from pypdf import PdfReader, PdfWriter

    w = PdfWriter(clone_from=PdfReader(io.BytesIO(dados)))
    for page in w.pages:
        w.update_page_form_field_values(page, valores, auto_regenerate=False)
    w.set_need_appearances_writer(True)
    b = io.BytesIO()
    w.write(b)
    with abrir(b.getvalue()) as pdf:
        pdf.generate_appearance_streams()
        return _salvar(pdf)


def achatar_formulario(dados: bytes) -> bytes:
    with abrir(dados) as pdf:
        pdf.generate_appearance_streams()
        pdf.flatten_annotations("all")
        if "/AcroForm" in pdf.Root:
            del pdf.Root["/AcroForm"]
        return _salvar(pdf)


# --------------------------------------------------------------------------
# Texto existente (para a função "editar texto existente")
# --------------------------------------------------------------------------
def texto_na_area(dados: bytes, pagina: int, x: float, y: float, w: float, h: float) -> str:
    """Texto sob um retângulo do quadro visível (melhor esforço)."""
    import pypdfium2 as pdfium
    from pypdf import PdfReader

    from .overlay import ponto_visivel_para_pdf

    pg = PdfReader(io.BytesIO(dados)).pages[pagina]
    xa, ya = ponto_visivel_para_pdf(pg, x, y)
    xb, yb = ponto_visivel_para_pdf(pg, x + w, y + h)
    doc = pdfium.PdfDocument(dados)
    try:
        page = doc[pagina]
        tp = page.get_textpage()
        try:
            return tp.get_text_bounded(min(xa, xb), min(ya, yb), max(xa, xb), max(ya, yb)).strip()
        finally:
            tp.close()
            page.close()
    finally:
        doc.close()
