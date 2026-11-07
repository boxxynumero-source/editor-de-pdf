"""Conversões imagem <-> PDF e tratamento de assinaturas."""
from __future__ import annotations

import io
import os

from PIL import Image, ImageOps
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .pdfops import PdfError


def _abrir_rgb(caminho: str) -> Image.Image:
    try:
        im = ImageOps.exif_transpose(Image.open(caminho))
    except Exception as e:
        raise PdfError(f"Não foi possível abrir a imagem “{os.path.basename(caminho)}”: {e}") from e
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        fundo = Image.new("RGB", im.size, "white")
        fundo.paste(im, mask=im.split()[3])
        return fundo
    return im.convert("RGB")


def imagens_para_pdf(caminhos: list[str], ajustar_a4: bool = True, progresso=None) -> bytes:
    if not caminhos:
        raise PdfError("Nenhuma imagem selecionada.")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pageCompression=1)
    for n, caminho in enumerate(caminhos):
        im = _abrir_rgb(caminho)
        jpg = io.BytesIO()
        im.save(jpg, "JPEG", quality=92)
        jpg.seek(0)
        iw, ih = im.size
        if ajustar_a4:
            pw, ph = A4 if iw <= ih else (A4[1], A4[0])
            m = 28.0
            r = min((pw - 2 * m) / iw, (ph - 2 * m) / ih)
            w, h = iw * r, ih * r
            c.setPageSize((pw, ph))
            c.drawImage(ImageReader(jpg), (pw - w) / 2, (ph - h) / 2, w, h)
        else:
            w, h = iw * 72 / 150, ih * 72 / 150
            c.setPageSize((w, h))
            c.drawImage(ImageReader(jpg), 0, 0, w, h)
        c.showPage()
        if progresso:
            progresso(n + 1, len(caminhos))
    c.save()
    return buf.getvalue()


def pdf_para_imagens(dados: bytes, pasta: str, prefixo: str, dpi: int = 150,
                     formato: str = "png", paginas=None, progresso=None) -> list[str]:
    import pypdfium2 as pdfium

    formato = formato.lower()
    os.makedirs(pasta, exist_ok=True)
    doc = pdfium.PdfDocument(dados)
    gerados = []
    try:
        total = len(doc)
        paginas = list(range(total)) if paginas is None else list(paginas)
        casas = len(str(total))
        for n, i in enumerate(paginas):
            page = doc[i]
            try:
                pil = page.render(scale=dpi / 72.0).to_pil().convert("RGB")
            finally:
                page.close()
            ext = "jpg" if formato in ("jpg", "jpeg") else "png"
            destino = os.path.join(pasta, f"{prefixo}_{i + 1:0{casas}d}.{ext}")
            if ext == "jpg":
                pil.save(destino, "JPEG", quality=92, dpi=(dpi, dpi))
            else:
                pil.save(destino, "PNG", dpi=(dpi, dpi))
            gerados.append(destino)
            if progresso:
                progresso(n + 1, len(paginas))
    finally:
        doc.close()
    return gerados


def recortar_png(dados: bytes) -> bytes:
    """Recorta as margens transparentes de um PNG (para assinaturas)."""
    im = Image.open(io.BytesIO(dados)).convert("RGBA")
    box = im.split()[3].getbbox()
    if box:
        im = im.crop(box)
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def remover_fundo_branco(dados: bytes, limiar: int = 200) -> bytes:
    """Torna transparente o fundo claro (útil para assinatura escaneada) e recorta."""
    im = Image.open(io.BytesIO(dados)).convert("RGBA")
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            lum = (r * 299 + g * 587 + b * 114) // 1000
            if lum >= limiar:
                px[x, y] = (r, g, b, 0)
    b = io.BytesIO()
    im.save(b, "PNG")
    return recortar_png(b.getvalue())
