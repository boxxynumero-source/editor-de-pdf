"""Aplica camadas (texto, imagens, anotações, marca d'água, numeração) e
tarjas (redação) sobre um PDF."""
from __future__ import annotations

import io
import math
from collections import defaultdict
from typing import Callable

import pikepdf
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .model import ALTURA_LINHA, ASCENDENTE, PAD_NOTA, Item, nome_fonte, sanitizar, tamanho_texto


# --------------------------------------------------------------------------
# Geometria: quadro visível (y para baixo) -> espaço do PDF
# --------------------------------------------------------------------------
def _geometria(page):
    rot = int(page.rotation or 0) % 360
    cb = page.cropbox
    x0, y0, x1, y1 = float(cb.left), float(cb.bottom), float(cb.right), float(cb.top)
    w, h = x1 - x0, y1 - y0
    vw, vh = (w, h) if rot in (0, 180) else (h, w)
    if rot == 0:
        m = (1, 0, 0, -1, x0, y1)
    elif rot == 90:
        m = (0, 1, 1, 0, x0, y0)
    elif rot == 180:
        m = (-1, 0, 0, 1, x0 + w, y0)
    else:  # 270
        m = (0, -1, -1, 0, x0 + w, y0 + h)
    return vw, vh, m


def ponto_visivel_para_pdf(page, x, y):
    _, _, (a, b, c, d, e, f) = _geometria(page)
    return (a * x + c * y + e, b * x + d * y + f)


# --------------------------------------------------------------------------
# Desenho de itens (canvas já no quadro visível)
# --------------------------------------------------------------------------
def _texto_reto(c, x, y_baseline, txt, fonte, tam, modo="left"):
    c.saveState()
    c.translate(x, y_baseline)
    c.scale(1, -1)
    c.setFont(fonte, tam)
    if modo == "center":
        c.drawCentredString(0, 0, txt)
    elif modo == "right":
        c.drawRightString(0, 0, txt)
    else:
        c.drawString(0, 0, txt)
    c.restoreState()


def desenhar_item(c, it: Item):
    k = it.kind
    c.saveState()
    try:
        if k in ("text", "note"):
            w, h = tamanho_texto(it)
            pad = PAD_NOTA if k == "note" else 0.0
            if it.fill:
                c.setFillColor(HexColor(it.fill))
                c.rect(it.x, it.y, w, h, stroke=0, fill=1)
                if k == "note":
                    c.setStrokeColor(HexColor("#C9B458"))
                    c.setLineWidth(0.6)
                    c.rect(it.x, it.y, w, h, stroke=1, fill=0)
            c.setFillColor(HexColor(it.color))
            fn = nome_fonte(it.font, it.bold, it.italic)
            for i, linha in enumerate(it.linhas()):
                base = it.y + pad + it.size * ASCENDENTE + i * it.size * ALTURA_LINHA
                _texto_reto(c, it.x + pad, base, linha, fn, it.size)
        elif k == "highlight":
            c.setFillColor(HexColor(it.color))
            c.setFillAlpha(0.4)
            c.rect(it.x, it.y, it.w, it.h, stroke=0, fill=1)
        elif k in ("underline", "strike"):
            c.setStrokeColor(HexColor(it.color))
            c.setLineWidth(max(it.width, 0.5))
            yy = it.y + it.h if k == "underline" else it.y + it.h / 2
            c.line(it.x, yy, it.x + it.w, yy)
        elif k in ("rect", "ellipse"):
            tem_traco = it.width > 0
            if it.fill:
                c.setFillColor(HexColor(it.fill))
            if tem_traco:
                c.setStrokeColor(HexColor(it.color))
                c.setLineWidth(it.width)
            if k == "rect":
                c.rect(it.x, it.y, it.w, it.h, stroke=int(tem_traco), fill=int(bool(it.fill)))
            else:
                c.ellipse(it.x, it.y, it.x + it.w, it.y + it.h, stroke=int(tem_traco), fill=int(bool(it.fill)))
        elif k == "pen" and len(it.points) >= 2:
            c.setStrokeColor(HexColor(it.color))
            c.setLineWidth(it.width)
            c.setLineJoin(1)
            c.setLineCap(1)
            p = c.beginPath()
            p.moveTo(*it.points[0])
            for pt in it.points[1:]:
                p.lineTo(*pt)
            c.drawPath(p, stroke=1, fill=0)
        elif k == "arrow" and len(it.points) >= 2:
            (x1, y1), (x2, y2) = it.points[0], it.points[-1]
            c.setStrokeColor(HexColor(it.color))
            c.setFillColor(HexColor(it.color))
            c.setLineWidth(it.width)
            ang = math.atan2(y2 - y1, x2 - x1)
            tam = max(8.0, it.width * 4.5)
            bx, by = x2 - tam * 0.8 * math.cos(ang), y2 - tam * 0.8 * math.sin(ang)
            c.line(x1, y1, bx, by)
            p = c.beginPath()
            p.moveTo(x2, y2)
            for da in (math.pi - 0.45, math.pi + 0.45):
                p.lineTo(x2 + tam * math.cos(ang + da), y2 + tam * math.sin(ang + da))
            p.close()
            c.drawPath(p, stroke=0, fill=1)
        elif k == "image" and it.image:
            c.translate(it.x, it.y + it.h)
            c.scale(1, -1)
            c.drawImage(ImageReader(io.BytesIO(it.image)), 0, 0, it.w, it.h, mask="auto")
    finally:
        c.restoreState()


# --------------------------------------------------------------------------
# Aplicação genérica
# --------------------------------------------------------------------------
Desenhista = Callable[[object, float, float], None]  # (canvas, largura_visivel, altura_visivel)


def aplicar_desenhos(dados: bytes, por_pagina: dict) -> bytes:
    """por_pagina: {indice_da_pagina: [funcao(c, vw, vh), ...]}"""
    if not por_pagina:
        return dados
    reader = PdfReader(io.BytesIO(dados))
    writer = PdfWriter(clone_from=reader)
    indices = sorted(por_pagina)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pageCompression=1)
    for i in indices:
        pg = writer.pages[i]
        vw, vh, (a, b, cc, d, e, f) = _geometria(pg)
        mb = pg.mediabox
        c.setPageSize((max(float(mb.right), 1.0), max(float(mb.top), 1.0)))
        c.saveState()
        c.transform(a, b, cc, d, e, f)
        for fn in por_pagina[i]:
            fn(c, vw, vh)
        c.restoreState()
        c.showPage()
    c.save()
    buf.seek(0)
    ov = PdfReader(buf)
    for k, i in enumerate(indices):
        writer.pages[i].merge_page(ov.pages[k])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def aplicar_itens(dados: bytes, itens: list) -> bytes:
    """Aplica itens de edição; as tarjas (kind == 'tarja') são aplicadas por
    último e REMOVEM o conteúdo por baixo."""
    normais = [i for i in itens if i.kind != "tarja"]
    tarjas = [i for i in itens if i.kind == "tarja"]
    por = defaultdict(list)
    for it in normais:
        por[it.page].append(lambda c, vw, vh, it=it: desenhar_item(c, it))
    out = aplicar_desenhos(dados, por)
    if tarjas:
        t = defaultdict(list)
        for it in tarjas:
            x, y, w, h = it.bbox()
            t[it.page].append((x, y, w, h, it.color or "#000000"))
        out = aplicar_tarjas(out, t)
    return out


# --------------------------------------------------------------------------
# Marca d'água e numeração
# --------------------------------------------------------------------------
def marca_dagua_texto(dados, texto, paginas, tamanho=60, opacidade=0.25, angulo=45, cor="#808080"):
    texto = sanitizar(texto)

    def fazer(c, vw, vh):
        c.saveState()
        c.setFillColor(HexColor(cor))
        c.setFillAlpha(opacidade)
        c.translate(vw / 2, vh / 2)
        c.rotate(-angulo)  # quadro y-para-baixo: negativo = anti-horário visual
        _texto_reto(c, 0, tamanho * 0.35, texto, "Helvetica-Bold", tamanho, "center")
        c.restoreState()

    return aplicar_desenhos(dados, {i: [fazer] for i in paginas})


def marca_dagua_imagem(dados, imagem: bytes, paginas, escala=0.6, opacidade=0.3):
    from PIL import Image

    iw, ih = Image.open(io.BytesIO(imagem)).size

    def fazer(c, vw, vh):
        w = vw * escala
        h = w * ih / iw
        if h > vh * escala:
            h = vh * escala
            w = h * iw / ih
        c.saveState()
        c.setFillAlpha(opacidade)
        c.translate((vw - w) / 2, (vh - h) / 2 + h)
        c.scale(1, -1)
        c.drawImage(ImageReader(io.BytesIO(imagem)), 0, 0, w, h, mask="auto")
        c.restoreState()

    return aplicar_desenhos(dados, {i: [fazer] for i in paginas})


POSICOES = ["Rodapé centralizado", "Rodapé à direita", "Rodapé à esquerda",
            "Cabeçalho centralizado", "Cabeçalho à direita", "Cabeçalho à esquerda"]


def numerar_paginas(dados, formato="Página {n} de {total}", posicao=0, inicio=1,
                    paginas=None, tamanho=10, cor="#000000", margem=24):
    total = len(PdfReader(io.BytesIO(dados)).pages)
    paginas = list(range(total)) if paginas is None else list(paginas)
    por = {}
    for ordem, i in enumerate(paginas):
        n = inicio + ordem
        txt = sanitizar(formato.replace("{n}", str(n)).replace("{total}", str(inicio + len(paginas) - 1)))

        def fazer(c, vw, vh, txt=txt):
            c.setFillColor(HexColor(cor))
            base = vh - margem if posicao < 3 else margem + tamanho
            modo = ("center", "right", "left")[posicao % 3]
            x = {"center": vw / 2, "right": vw - margem, "left": margem}[modo]
            _texto_reto(c, x, base, txt, "Helvetica", tamanho, modo)

        por[i] = [fazer]
    return aplicar_desenhos(dados, por)


# --------------------------------------------------------------------------
# Redação verdadeira
# --------------------------------------------------------------------------
def aplicar_tarjas(dados: bytes, por_pagina: dict, dpi: int = 200, progresso=None) -> bytes:
    """Cada página com tarja é RASTERIZADA (com as tarjas pintadas) e substituída
    por uma página-imagem: o texto/vetores originais deixam de existir no
    arquivo. O documento é remontado do zero para não deixar objetos órfãos
    (marcadores, links, campos) que ainda apontem para o conteúdo antigo."""
    import pypdfium2 as pdfium
    from PIL import ImageDraw

    pdoc = pdfium.PdfDocument(dados)
    substitutas = {}
    try:
        escala = dpi / 72.0
        for n, (idx, rects) in enumerate(sorted(por_pagina.items())):
            page = pdoc[idx]
            try:
                pil = page.render(scale=escala).to_pil().convert("RGB")
            finally:
                page.close()
            d = ImageDraw.Draw(pil)
            for x, y, w, h, cor in rects:
                d.rectangle([x * escala, y * escala, (x + w) * escala, (y + h) * escala], fill=cor)
            b = io.BytesIO()
            pil.save(b, "PDF", resolution=float(dpi), quality=90)
            substitutas[idx] = b.getvalue()
            if progresso:
                progresso(n + 1, len(por_pagina))
    finally:
        pdoc.close()

    origem = pikepdf.Pdf.open(io.BytesIO(dados))
    novo = pikepdf.Pdf.new()
    abertos = []
    for i in range(len(origem.pages)):
        if i in substitutas:
            s = pikepdf.Pdf.open(io.BytesIO(substitutas[i]))
            abertos.append(s)
            novo.pages.append(s.pages[0])
        else:
            novo.pages.append(origem.pages[i])
    out = io.BytesIO()
    novo.save(out, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    return out.getvalue()
