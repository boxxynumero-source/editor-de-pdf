"""Visualizador contínuo com renderização sob demanda, cache e ferramentas de edição."""
from __future__ import annotations

import math
import threading
from collections import OrderedDict

import pypdfium2 as pdfium
from PySide6.QtCore import QPointF, QRectF, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from ..core.model import ALTURA_LINHA, ASCENDENTE, PAD_NOTA, TIPOS_REDIMENSIONAVEIS, Item, tamanho_texto
from .tasks import Tarefa

FAMILIA_QT = {"Helvetica": "Arial", "Times": "Times New Roman", "Courier": "Courier New"}
PX_POR_PT_100 = 96.0 / 72.0  # zoom 100% = tamanho "de tela" (96 dpi)
_cache_imagens: dict = {}


# --------------------------------------------------------------------------
class Renderizador:
    """Envolve o pdfium (que não é thread-safe) com um lock."""

    def __init__(self):
        self._lock = threading.RLock()
        self._pdf = None

    def carregar(self, dados: bytes):
        with self._lock:
            if self._pdf is not None:
                self._pdf.close()
            self._pdf = pdfium.PdfDocument(dados)

    def tamanhos(self):
        with self._lock:
            out = []
            for i in range(len(self._pdf)):
                pg = self._pdf[i]
                try:
                    out.append(tuple(pg.get_size()))
                finally:
                    pg.close()
            return out

    def renderizar(self, i: int, escala: float):
        with self._lock:
            if self._pdf is None or i >= len(self._pdf):
                return None
            pg = self._pdf[i]
            try:
                pil = pg.render(scale=escala).to_pil().convert("RGBA")
            finally:
                pg.close()
        w, h = pil.size
        return QImage(pil.tobytes("raw", "RGBA"), w, h, 4 * w, QImage.Format.Format_RGBA8888).copy()

    def fechar(self):
        with self._lock:
            if self._pdf is not None:
                self._pdf.close()
                self._pdf = None


# --------------------------------------------------------------------------
def _imagem_do_item(it: Item) -> QImage:
    chave = id(it.image)
    img = _cache_imagens.get(chave)
    if img is None:
        img = QImage.fromData(it.image)
        if len(_cache_imagens) > 40:
            _cache_imagens.clear()
        _cache_imagens[chave] = img
    return img


def desenhar_item_qt(p: QPainter, it: Item, esc: float):
    def S(v):
        return v * esc

    k = it.kind
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    cor = QColor(it.color)
    if k in ("text", "note"):
        w, h = tamanho_texto(it)
        pad = PAD_NOTA if k == "note" else 0.0
        if it.fill:
            r = QRectF(S(it.x), S(it.y), S(w), S(h))
            p.fillRect(r, QColor(it.fill))
            if k == "note":
                p.setPen(QPen(QColor("#C9B458"), 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(r)
        f = QFont(FAMILIA_QT.get(it.font, "Arial"))
        f.setPixelSize(max(1, int(round(S(it.size)))))
        f.setBold(it.bold)
        f.setItalic(it.italic)
        p.setFont(f)
        p.setPen(cor)
        for i, linha in enumerate(it.text.split("\n")):
            base = it.y + pad + it.size * ASCENDENTE + i * it.size * ALTURA_LINHA
            p.drawText(QPointF(S(it.x + pad), S(base)), linha)
    elif k == "highlight":
        c = QColor(it.color)
        c.setAlphaF(0.4)
        p.fillRect(QRectF(S(it.x), S(it.y), S(it.w), S(it.h)), c)
    elif k in ("underline", "strike"):
        p.setPen(QPen(cor, max(1.0, S(it.width))))
        yy = it.y + it.h if k == "underline" else it.y + it.h / 2
        p.drawLine(QPointF(S(it.x), S(yy)), QPointF(S(it.x + it.w), S(yy)))
    elif k in ("rect", "ellipse"):
        p.setPen(QPen(cor, max(1.0, S(it.width))) if it.width > 0 else QPen(Qt.PenStyle.NoPen))
        p.setBrush(QColor(it.fill) if it.fill else Qt.BrushStyle.NoBrush)
        r = QRectF(S(it.x), S(it.y), S(it.w), S(it.h))
        p.drawRect(r) if k == "rect" else p.drawEllipse(r)
    elif k == "pen" and len(it.points) >= 2:
        p.setPen(QPen(cor, max(1.0, S(it.width)), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline(QPolygonF([QPointF(S(x), S(y)) for x, y in it.points]))
    elif k == "arrow" and len(it.points) >= 2:
        (x1, y1), (x2, y2) = it.points[0], it.points[-1]
        ang = math.atan2(y2 - y1, x2 - x1)
        tam = max(8.0, it.width * 4.5)
        bx, by = x2 - tam * 0.8 * math.cos(ang), y2 - tam * 0.8 * math.sin(ang)
        p.setPen(QPen(cor, max(1.0, S(it.width)), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(S(x1), S(y1)), QPointF(S(bx), S(by)))
        pts = [QPointF(S(x2), S(y2))]
        for da in (math.pi - 0.45, math.pi + 0.45):
            pts.append(QPointF(S(x2 + tam * math.cos(ang + da)), S(y2 + tam * math.sin(ang + da))))
        p.setBrush(cor)
        p.drawPolygon(QPolygonF(pts))
    elif k == "image" and it.image:
        img = _imagem_do_item(it)
        if not img.isNull():
            p.drawImage(QRectF(S(it.x), S(it.y), S(it.w), S(it.h)), img)
    elif k == "tarja":
        r = QRectF(S(it.x), S(it.y), S(it.w), S(it.h))
        p.fillRect(r, QColor(it.color or "#000000"))
        p.setPen(QPen(QColor("#E53935"), 1, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)
    p.restore()


# --------------------------------------------------------------------------
class PaginaWidget(QWidget):
    def __init__(self, vista: "PdfVista", indice: int):
        super().__init__()
        self.vista = vista
        self.indice = indice
        self._modo = None
        self._ultimo = None
        self._registrado = False
        self._orig = None
        self._ini = None
        self._pontos: list = []
        self.setMouseTracking(False)

    # -- desenho -----------------------------------------------------------
    def paintEvent(self, _e):
        v = self.vista
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("white"))
        pm = v.pixmap_de(self.indice)
        if pm is not None:
            p.drawPixmap(self.rect(), pm)
        else:
            p.setPen(QColor("#999999"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"Página {self.indice + 1}")
        esc = v.escala
        if v.doc:
            for it in v.doc.itens:
                if it.page == self.indice:
                    desenhar_item_qt(p, it, esc)
            sel = v.selecionado
            if sel is not None and sel.page == self.indice and sel in v.doc.itens:
                x, y, w, h = sel.bbox()
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                p.setPen(QPen(QColor("#1E88E5"), 1, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(QRectF(x * esc - 3, y * esc - 3, w * esc + 6, h * esc + 6))
                if sel.kind in TIPOS_REDIMENSIONAVEIS:
                    p.setPen(QPen(QColor("#1E88E5"), 1))
                    p.setBrush(QColor("white"))
                    p.drawRect(self._alca(sel))
        self._previa(p)

    def _previa(self, p: QPainter):
        if self._ini is None or self.vista.ferramenta in ("selecionar",):
            return
        esc = self.vista.escala
        t = self.vista.ferramenta
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cor = QColor(self.vista.cor_realce if t == "realce" else ("#000000" if t == "tarja" else self.vista.cor))
        if t == "caneta" and len(self._pontos) > 1:
            p.setPen(QPen(cor, max(1.0, self.vista.espessura * esc), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPolyline(QPolygonF([QPointF(a.x() * esc, a.y() * esc) for a in self._pontos]))
        elif t == "seta" and self._pontos:
            p.setPen(QPen(cor, max(1.0, self.vista.espessura * esc)))
            p.drawLine(QPointF(self._ini.x() * esc, self._ini.y() * esc), QPointF(self._pontos[-1].x() * esc, self._pontos[-1].y() * esc))
        elif self._pontos:
            a, b = self._ini, self._pontos[-1]
            r = QRectF(min(a.x(), b.x()) * esc, min(a.y(), b.y()) * esc, abs(a.x() - b.x()) * esc, abs(a.y() - b.y()) * esc)
            if t in ("realce", "tarja"):
                c = QColor(cor)
                c.setAlphaF(0.4 if t == "realce" else 0.8)
                p.fillRect(r, c)
            p.setPen(QPen(cor, 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(r) if t == "circulo" else p.drawRect(r)

    def _alca(self, it: Item) -> QRectF:
        x, y, w, h = it.bbox()
        e = self.vista.escala
        return QRectF((x + w) * e - 2, (y + h) * e - 2, 10, 10)

    # -- mouse -------------------------------------------------------------
    def _pt(self, e) -> QPointF:
        pos = e.position()
        return QPointF(pos.x() / self.vista.escala, pos.y() / self.vista.escala)

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or not self.vista.doc:
            return
        v = self.vista
        v.setFocus()
        pt = self._pt(e)
        t = v.ferramenta
        self._registrado = False
        if t == "selecionar":
            sel = v.selecionado
            if sel is not None and sel.page == self.indice and sel.kind in TIPOS_REDIMENSIONAVEIS and self._alca(sel).contains(e.position()):
                self._modo = "redimensionar"
                self._orig = (sel.size, sel.bbox(), sel.w, sel.h)
                return
            hit = v.item_em(self.indice, pt)
            v.selecionar(hit)
            if hit is not None:
                self._modo = "mover"
                self._ultimo = pt
        elif t in ("texto", "nota", "imagem", "assinatura"):
            v.pedido_criar.emit(t, self.indice, pt.x(), pt.y(), 0.0, 0.0)
        else:
            self._ini = pt
            self._pontos = [pt]
            self._modo = "desenhar"

    def mouseMoveEvent(self, e):
        v = self.vista
        pt = self._pt(e)
        if self._modo == "mover" and v.selecionado is not None:
            if not self._registrado:
                v.doc.registrar()
                self._registrado = True
            v.selecionado.mover(pt.x() - self._ultimo.x(), pt.y() - self._ultimo.y())
            self._ultimo = pt
            self.update()
        elif self._modo == "redimensionar" and v.selecionado is not None:
            if not self._registrado:
                v.doc.registrar()
                self._registrado = True
            it = v.selecionado
            tam0, (bx, by, bw, bh), w0, h0 = self._orig
            if it.kind in ("text", "note"):
                it.size = max(4.0, min(300.0, tam0 * max(6.0, pt.y() - by) / max(bh, 1.0)))
            elif it.kind == "image":
                it.w = max(8.0, pt.x() - it.x)
                it.h = it.w * h0 / max(w0, 1.0)
            else:
                it.w = max(2.0, pt.x() - it.x)
                it.h = max(2.0, pt.y() - it.y)
            self.update()
        elif self._modo == "desenhar":
            if v.ferramenta == "caneta":
                self._pontos.append(pt)
            else:
                self._pontos = [pt]
            self.update()

    def mouseReleaseEvent(self, e):
        v = self.vista
        modo, self._modo = self._modo, None
        if modo == "desenhar" and self._ini is not None:
            ini, fim = self._ini, self._pontos[-1] if self._pontos else self._ini
            pontos = list(self._pontos)
            self._ini, self._pontos = None, []
            self._finalizar(ini, fim, pontos)
            self.update()
        elif modo in ("mover", "redimensionar"):
            v.doc.itens_mudaram.emit()

    def mouseDoubleClickEvent(self, e):
        v = self.vista
        if v.ferramenta == "selecionar" and v.doc:
            hit = v.item_em(self.indice, self._pt(e))
            if hit is not None and hit.kind in ("text", "note"):
                v.pedido_editar.emit(hit)

    def _finalizar(self, a: QPointF, b: QPointF, pontos: list):
        v = self.vista
        t = v.ferramenta
        x, y = min(a.x(), b.x()), min(a.y(), b.y())
        w, h = abs(a.x() - b.x()), abs(a.y() - b.y())
        i = self.indice
        it = None
        if t == "caneta":
            if len(pontos) >= 2:
                it = Item("pen", i, color=v.cor, width=v.espessura, points=[(q.x(), q.y()) for q in pontos])
        elif t == "seta":
            if math.hypot(w, h) > 6:
                it = Item("arrow", i, color=v.cor, width=v.espessura, points=[(a.x(), a.y()), (b.x(), b.y())])
        elif w > 3 and (h > 3 or t in ("sublinhar", "riscar")):
            if t == "realce":
                it = Item("highlight", i, x, y, w, h, color=v.cor_realce)
            elif t == "sublinhar":
                it = Item("underline", i, x, y, w, max(h, 0.0), color=v.cor, width=v.espessura)
            elif t == "riscar":
                it = Item("strike", i, x, y, w, max(h, 0.0), color=v.cor, width=v.espessura)
            elif t == "retangulo":
                it = Item("rect", i, x, y, w, h, color=v.cor, width=v.espessura)
            elif t == "circulo":
                it = Item("ellipse", i, x, y, w, h, color=v.cor, width=v.espessura)
            elif t == "tarja":
                it = Item("tarja", i, x, y, w, h, color="#000000")
            elif t == "editar_texto":
                v.pedido_criar.emit("editar_texto", i, x, y, w, h)
                return
        if it is not None:
            v.doc.adicionar_item(it)
            v.selecionar(it)


# --------------------------------------------------------------------------
class PdfVista(QScrollArea):
    pagina_mudou = Signal(int)
    zoom_mudou = Signal(float)
    pedido_criar = Signal(str, int, float, float, float, float)
    pedido_editar = Signal(object)
    selecao_mudou = Signal(object)
    paginas_prontas = Signal()

    def __init__(self):
        super().__init__()
        self.doc = None
        self.escala = PX_POR_PT_100
        self.modo_zoom = "largura"
        self._ferramenta = "selecionar"
        self.cor = "#E53935"
        self.cor_realce = "#FFEB3B"
        self.espessura = 2.0
        self.selecionado = None
        self.renderizador = Renderizador()
        self._cache: OrderedDict = OrderedDict()
        self._fallback: dict = {}
        self._pendentes: set = set()
        self._visiveis: set = set()
        self._tarefas: set = set()
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(1)
        self._paginas: list[PaginaWidget] = []
        self._tamanhos: list = []
        self._versao = -1
        self._pagina_atual = 0

        cont = QWidget()
        cont.setAutoFillBackground(True)
        pal = cont.palette()
        pal.setColor(cont.backgroundRole(), QColor("#7d8085"))
        cont.setPalette(pal)
        lay = QVBoxLayout(cont)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(14)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._lay = lay
        self.setWidget(cont)
        self.setWidgetResizable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.verticalScrollBar().valueChanged.connect(self._atualizar_visiveis)
        self._timer_resize = QTimer(self)
        self._timer_resize.setSingleShot(True)
        self._timer_resize.timeout.connect(self._reajustar)

    # -- propriedades ------------------------------------------------------
    @property
    def zoom(self) -> float:
        return self.escala / PX_POR_PT_100

    @property
    def ferramenta(self) -> str:
        return self._ferramenta

    @ferramenta.setter
    def ferramenta(self, t: str):
        self._ferramenta = t
        cur = Qt.CursorShape.ArrowCursor if t == "selecionar" else Qt.CursorShape.CrossCursor
        for w in self._paginas:
            w.setCursor(cur)
        if t != "selecionar":
            self.selecionar(None)

    # -- documento ---------------------------------------------------------
    def set_documento(self, doc):
        if self.doc is not None:
            try:
                self.doc.estrutura_mudou.disconnect(self.reconstruir)
                self.doc.itens_mudaram.disconnect(self._repintar)
            except (RuntimeError, TypeError):
                pass
        self.doc = doc
        self.selecionado = None
        if doc is not None:
            doc.estrutura_mudou.connect(self.reconstruir)
            doc.itens_mudaram.connect(self._repintar)
            self.modo_zoom = "largura"
            self.reconstruir(inicial=True)
        else:
            self._limpar()

    def _limpar(self):
        for w in self._paginas:
            self._lay.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self._paginas = []
        self._tamanhos = []
        self._cache.clear()
        self._fallback.clear()
        self._pendentes.clear()

    def reconstruir(self, inicial: bool = False):
        if self.doc is None:
            return
        pag = 0 if inicial else self._pagina_atual
        self._limpar()
        self.renderizador.carregar(self.doc.dados)
        self._versao = self.doc.versao
        self._tamanhos = self.renderizador.tamanhos()
        cur = Qt.CursorShape.ArrowCursor if self._ferramenta == "selecionar" else Qt.CursorShape.CrossCursor
        for i in range(len(self._tamanhos)):
            w = PaginaWidget(self, i)
            w.setCursor(cur)
            self._paginas.append(w)
            self._lay.addWidget(w, 0, Qt.AlignmentFlag.AlignHCenter)
        if self.modo_zoom != "livre":
            self._calcular_escala_modo(pag)
        self._aplicar_tamanhos()
        self.paginas_prontas.emit()
        QTimer.singleShot(0, lambda: (self.ir_para(min(pag, len(self._paginas) - 1)), self._atualizar_visiveis()))

    # -- zoom --------------------------------------------------------------
    def _aplicar_tamanhos(self):
        for w, (pw, ph) in zip(self._paginas, self._tamanhos):
            w.setFixedSize(max(1, int(pw * self.escala)), max(1, int(ph * self.escala)))
        self.zoom_mudou.emit(self.zoom)

    def _calcular_escala_modo(self, pag: int):
        if not self._tamanhos:
            return
        pag = min(max(pag, 0), len(self._tamanhos) - 1)
        pw, ph = self._tamanhos[pag]
        larg = self.viewport().width() - 44
        if self.modo_zoom == "largura":
            e = larg / pw
        else:
            e = min(larg / pw, (self.viewport().height() - 32) / ph)
        self.escala = min(max(e, 0.15), 8.0)

    def _mudar_escala(self, e: float):
        e = min(max(e, 0.15), 8.0)
        cont = self.widget()
        frac = self.verticalScrollBar().value() / max(1, cont.height())
        self.escala = e
        self._aplicar_tamanhos()
        cont.layout().activate()
        self.verticalScrollBar().setValue(int(frac * cont.height()))
        self._atualizar_visiveis()

    def definir_zoom(self, z: float):
        self.modo_zoom = "livre"
        self._mudar_escala(z * PX_POR_PT_100)

    def ajustar_largura(self):
        self.modo_zoom = "largura"
        self._reajustar()

    def ajustar_pagina(self):
        self.modo_zoom = "pagina"
        self._reajustar()

    def _reajustar(self):
        if self.modo_zoom == "livre" or not self._tamanhos:
            return
        self._calcular_escala_modo(self._pagina_atual)
        self._mudar_escala(self.escala)
        self.ir_para(self._pagina_atual)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.modo_zoom != "livre":
            self._timer_resize.start(120)
        self._atualizar_visiveis()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            d = e.angleDelta().y()
            if d:
                self.definir_zoom(self.zoom * (1.1 ** (d / 120.0)))
            e.accept()
        else:
            super().wheelEvent(e)

    # -- navegação ---------------------------------------------------------
    def ir_para(self, i: int):
        if not self._paginas:
            return
        i = min(max(i, 0), len(self._paginas) - 1)
        self.verticalScrollBar().setValue(max(0, self._paginas[i].y() - 12))
        self._pagina_atual = i
        self.pagina_mudou.emit(i)

    def pagina_atual(self) -> int:
        return self._pagina_atual

    def total_paginas(self) -> int:
        return len(self._paginas)

    # -- renderização sob demanda -----------------------------------------
    def _chave(self, i: int):
        return (self._versao, i, round(self.escala * self.devicePixelRatioF(), 3))

    def pixmap_de(self, i: int):
        pm = self._cache.get(self._chave(i))
        return pm if pm is not None else self._fallback.get(i)

    def _atualizar_visiveis(self, *_):
        if not self._paginas:
            return
        top = self.verticalScrollBar().value()
        vh = self.viewport().height()
        margem = vh // 2
        vis = set()
        atual = None
        centro = top + vh // 2
        for w in self._paginas:
            y0, y1 = w.y(), w.y() + w.height()
            if y1 > top - margem and y0 < top + vh + margem:
                vis.add(w.indice)
            if atual is None and centro < y1 + 7:
                atual = w.indice
        if atual is None:
            atual = len(self._paginas) - 1
        self._visiveis = vis
        for i in sorted(vis):
            self._pedir(i)
        if atual != self._pagina_atual:
            self._pagina_atual = atual
            self.pagina_mudou.emit(atual)

    def _pedir(self, i: int):
        chave = self._chave(i)
        if chave in self._cache:
            self._cache.move_to_end(chave)
            return
        if chave in self._pendentes:
            return
        self._pendentes.add(chave)
        esc = chave[2]

        def trabalho():
            if i not in self._visiveis or chave[0] != self._versao:
                return (chave, None)
            return (chave, self.renderizador.renderizar(i, esc))

        t = Tarefa(trabalho)
        self._tarefas.add(t)
        t.sinais.concluido.connect(lambda r, t=t: self._recebido(r, t))
        t.sinais.erro.connect(lambda _e, t=t, c=chave: (self._tarefas.discard(t), self._pendentes.discard(c)))
        self._pool.start(t)

    def _recebido(self, r, tarefa):
        self._tarefas.discard(tarefa)
        chave, img = r
        self._pendentes.discard(chave)
        if img is None:
            if chave[0] == self._versao and chave[1] in self._visiveis:
                QTimer.singleShot(50, lambda: self._pedir(chave[1]))
            return
        if chave[0] != self._versao:
            return
        pm = QPixmap.fromImage(img)
        self._cache[chave] = pm
        while len(self._cache) > 60:
            self._cache.popitem(last=False)
        self._fallback[chave[1]] = pm
        if chave[1] < len(self._paginas):
            self._paginas[chave[1]].update()

    # -- itens -------------------------------------------------------------
    def item_em(self, pagina: int, pt: QPointF):
        if not self.doc:
            return None
        m = 4.0 / max(self.escala, 0.1)
        for it in reversed(self.doc.itens):
            if it.page != pagina:
                continue
            x, y, w, h = it.bbox()
            if it.kind in ("pen", "arrow", "underline", "strike"):
                h = max(h, 6.0)
                y = y - (3.0 if it.kind != "underline" else 0)
            if x - m <= pt.x() <= x + w + m and y - m <= pt.y() <= y + h + m:
                return it
        return None

    def selecionar(self, it):
        if self.selecionado is it:
            return
        self.selecionado = it
        self._repintar()
        self.selecao_mudou.emit(it)

    def _repintar(self):
        if self.doc is not None and self.selecionado is not None and self.selecionado not in self.doc.itens:
            self.selecionado = None
            self.selecao_mudou.emit(None)
        for i in self._visiveis:
            if i < len(self._paginas):
                self._paginas[i].update()

    def excluir_selecao(self):
        if self.doc is not None and self.selecionado is not None:
            it, self.selecionado = self.selecionado, None
            self.doc.remover_item(it)
            self.selecao_mudou.emit(None)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.excluir_selecao()
        elif e.key() == Qt.Key.Key_Escape:
            self.selecionar(None)
        else:
            super().keyPressEvent(e)
