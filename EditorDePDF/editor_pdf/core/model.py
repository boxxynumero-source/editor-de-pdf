"""Modelo de itens de edição (texto, imagens, anotações) em coordenadas do
quadro VISÍVEL da página: origem no canto superior esquerdo, y para baixo,
unidade = ponto PDF (1/72 pol), já considerando a rotação da página."""
from __future__ import annotations

from dataclasses import dataclass, field

from reportlab.pdfbase import pdfmetrics

FONTES = {
    "Helvetica": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"),
    "Times": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
    "Courier": ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"),
}
ROTULOS_FONTES = {"Helvetica": "Helvetica (tipo Arial)", "Times": "Times (com serifa)", "Courier": "Courier (monoespaçada)"}

TIPOS_REDIMENSIONAVEIS = {"text", "note", "image", "highlight", "underline", "strike", "rect", "ellipse"}
ALTURA_LINHA = 1.2
ASCENDENTE = 0.9
PAD_NOTA = 4.0


def nome_fonte(familia: str, negrito: bool, italico: bool) -> str:
    f = FONTES.get(familia, FONTES["Helvetica"])
    return f[(1 if negrito else 0) + (2 if italico else 0)]


def sanitizar(texto: str) -> str:
    """Fontes padrão do PDF só cobrem Latin-1/WinAnsi (acentos do português OK)."""
    return texto.encode("cp1252", "replace").decode("cp1252")


@dataclass
class Item:
    kind: str  # text note image highlight underline strike pen rect ellipse arrow tarja
    page: int
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    color: str = "#000000"
    fill: str = ""
    alpha: float = 1.0
    width: float = 1.5
    text: str = ""
    font: str = "Helvetica"
    size: float = 12.0
    bold: bool = False
    italic: bool = False
    points: list = field(default_factory=list)
    image: bytes = b""

    def linhas(self):
        return sanitizar(self.text).split("\n")

    def bbox(self):
        """(x, y, w, h) no quadro visível."""
        if self.kind in ("text", "note"):
            w, h = tamanho_texto(self)
            return (self.x, self.y, w, h)
        if self.kind in ("pen", "arrow") and self.points:
            xs = [p[0] for p in self.points]
            ys = [p[1] for p in self.points]
            return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        return (self.x, self.y, self.w, self.h)

    def mover(self, dx: float, dy: float):
        self.x += dx
        self.y += dy
        self.points = [(px + dx, py + dy) for px, py in self.points]


def tamanho_texto(it: Item):
    fn = nome_fonte(it.font, it.bold, it.italic)
    linhas = it.linhas()
    w = max((pdfmetrics.stringWidth(l, fn, it.size) for l in linhas), default=0.0)
    h = len(linhas) * it.size * ALTURA_LINHA
    if it.kind == "note":
        w += 2 * PAD_NOTA
        h += 2 * PAD_NOTA
    return (max(w, 1.0), max(h, 1.0))
