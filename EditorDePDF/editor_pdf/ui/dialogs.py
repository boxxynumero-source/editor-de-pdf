"""Caixas de diálogo (todas em português do Brasil)."""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QRadioButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from ..core import imagens
from ..core.model import ROTULOS_FONTES
from ..core.overlay import POSICOES
from .tasks import pasta_dados


def _botoes(dlg, ok="OK"):
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.button(QDialogButtonBox.StandardButton.Ok).setText(ok)
    bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


class BotaoCor(QPushButton):
    def __init__(self, cor="#000000"):
        super().__init__()
        self.cor = cor
        self.setFixedWidth(60)
        self.clicked.connect(self._escolher)
        self._pintar()

    def _pintar(self):
        self.setStyleSheet(f"background:{self.cor}; border:1px solid #888; min-height:20px;")

    def _escolher(self):
        c = QColorDialog.getColor(QColor(self.cor), self, "Escolher cor")
        if c.isValid():
            self.cor = c.name()
            self._pintar()


def escolher_pasta(parent, linha: QLineEdit):
    d = QFileDialog.getExistingDirectory(parent, "Escolher pasta", linha.text() or os.path.expanduser("~"))
    if d:
        linha.setText(d)


def _linha_pasta(parent):
    h = QHBoxLayout()
    e = QLineEdit(os.path.join(os.path.expanduser("~"), "Documents"))
    b = QPushButton("Procurar…")
    b.clicked.connect(lambda: escolher_pasta(parent, e))
    h.addWidget(e, 1)
    h.addWidget(b)
    return h, e


# --------------------------------------------------------------------------
class TextoDialog(QDialog):
    def __init__(self, parent, titulo="Adicionar texto", texto="", familia="Helvetica", tamanho=14.0,
                 cor="#000000", negrito=False, italico=False, so_texto=False, aviso=None, opcao=None):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        if aviso:
            lb = QLabel(aviso)
            lb.setWordWrap(True)
            lb.setStyleSheet("color:#b26a00;")
            lay.addWidget(lb)
        self.txt = QPlainTextEdit(texto)
        self.txt.setMinimumHeight(90)
        lay.addWidget(self.txt)
        form = QFormLayout()
        self.fonte = QComboBox()
        for k, rot in ROTULOS_FONTES.items():
            self.fonte.addItem(rot, k)
        self.fonte.setCurrentIndex(max(0, self.fonte.findData(familia)))
        self.tam = QDoubleSpinBox()
        self.tam.setRange(4, 300)
        self.tam.setValue(tamanho)
        self.cor = BotaoCor(cor)
        self.neg = QCheckBox("Negrito")
        self.neg.setChecked(negrito)
        self.ita = QCheckBox("Itálico")
        self.ita.setChecked(italico)
        if not so_texto:
            form.addRow("Fonte:", self.fonte)
            form.addRow("Tamanho:", self.tam)
            form.addRow("Cor:", self.cor)
            h = QHBoxLayout()
            h.addWidget(self.neg)
            h.addWidget(self.ita)
            form.addRow("Estilo:", h)
        lay.addLayout(form)
        self.chk = None
        if opcao:
            self.chk = QCheckBox(opcao)
            self.chk.setChecked(True)
            lay.addWidget(self.chk)
        lay.addWidget(_botoes(self))
        self.txt.setFocus()

    def valores(self):
        return {"text": self.txt.toPlainText(), "font": self.fonte.currentData(), "size": self.tam.value(),
                "color": self.cor.cor, "bold": self.neg.isChecked(), "italic": self.ita.isChecked(),
                "remover": bool(self.chk and self.chk.isChecked())}


# --------------------------------------------------------------------------
def pasta_assinaturas() -> str:
    p = os.path.join(pasta_dados(), "assinaturas")
    os.makedirs(p, exist_ok=True)
    return p


class AreaDesenho(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(440, 170)
        self.img = QImage(self.size(), QImage.Format.Format_ARGB32)
        self.img.fill(Qt.GlobalColor.transparent)
        self.ultimo = None
        self.tem_traco = False
        self.setCursor(Qt.CursorShape.CrossCursor)

    def limpar(self):
        self.img.fill(Qt.GlobalColor.transparent)
        self.tem_traco = False
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("white"))
        p.setPen(QPen(QColor("#cccccc"), 1, Qt.PenStyle.DashLine))
        p.drawLine(16, self.height() - 40, self.width() - 16, self.height() - 40)
        p.drawImage(0, 0, self.img)
        p.setPen(QColor("#999999"))
        if not self.tem_traco:
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Desenhe sua assinatura aqui com o mouse")

    def mousePressEvent(self, e):
        self.ultimo = e.position()
        self._ponto(self.ultimo, self.ultimo)

    def mouseMoveEvent(self, e):
        if self.ultimo is not None:
            self._ponto(self.ultimo, e.position())
            self.ultimo = e.position()

    def mouseReleaseEvent(self, _e):
        self.ultimo = None

    def _ponto(self, a, b):
        p = QPainter(self.img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor("#111111"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawLine(QPointF(a), QPointF(b))
        p.end()
        self.tem_traco = True
        self.update()

    def png(self) -> bytes:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        self.img.save(buf, "PNG")
        return bytes(ba.data())


class AssinaturaDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Assinatura")
        self.png: bytes | None = None
        lay = QHBoxLayout(self)

        esq = QVBoxLayout()
        esq.addWidget(QLabel("Assinaturas salvas:"))
        self.lista = QListWidget()
        self.lista.setIconSize(QSize(120, 48))
        self.lista.setMinimumWidth(200)
        self.lista.itemDoubleClicked.connect(lambda *_: self._usar_salva())
        esq.addWidget(self.lista, 1)
        b1 = QPushButton("Usar a selecionada")
        b1.clicked.connect(self._usar_salva)
        b2 = QPushButton("Excluir selecionada")
        b2.clicked.connect(self._excluir)
        esq.addWidget(b1)
        esq.addWidget(b2)
        lay.addLayout(esq)

        dir_ = QVBoxLayout()
        dir_.addWidget(QLabel("Nova assinatura:"))
        self.area = AreaDesenho()
        dir_.addWidget(self.area)
        h = QHBoxLayout()
        bl = QPushButton("Limpar")
        bl.clicked.connect(self.area.limpar)
        bs = QPushButton("Salvar e usar o desenho")
        bs.clicked.connect(self._usar_desenho)
        h.addWidget(bl)
        h.addWidget(bs)
        dir_.addLayout(h)
        dir_.addSpacing(8)
        self.fundo = QCheckBox("Ao importar, remover o fundo branco")
        self.fundo.setChecked(True)
        bi = QPushButton("Importar imagem da assinatura…")
        bi.clicked.connect(self._importar)
        dir_.addWidget(self.fundo)
        dir_.addWidget(bi)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        dir_.addWidget(cancel)
        lay.addLayout(dir_)
        self._carregar()

    def _carregar(self):
        self.lista.clear()
        pasta = pasta_assinaturas()
        for nome in sorted(os.listdir(pasta)):
            if nome.lower().endswith(".png"):
                caminho = os.path.join(pasta, nome)
                it = QListWidgetItem(QIcon(QPixmap(caminho)), "")
                it.setData(Qt.ItemDataRole.UserRole, caminho)
                self.lista.addItem(it)

    def _salvar(self, dados: bytes):
        caminho = os.path.join(pasta_assinaturas(), f"assinatura_{int(time.time() * 1000)}.png")
        with open(caminho, "wb") as f:
            f.write(dados)

    def _usar_salva(self):
        it = self.lista.currentItem()
        if it:
            with open(it.data(Qt.ItemDataRole.UserRole), "rb") as f:
                self.png = f.read()
            self.accept()

    def _excluir(self):
        it = self.lista.currentItem()
        if it:
            try:
                os.remove(it.data(Qt.ItemDataRole.UserRole))
            except OSError:
                pass
            self._carregar()

    def _usar_desenho(self):
        if not self.area.tem_traco:
            QMessageBox.information(self, "Assinatura", "Desenhe a assinatura na área branca primeiro.")
            return
        self.png = imagens.recortar_png(self.area.png())
        self._salvar(self.png)
        self.accept()

    def _importar(self):
        arq, _ = QFileDialog.getOpenFileName(self, "Importar assinatura", "", "Imagens (*.png *.jpg *.jpeg *.bmp)")
        if not arq:
            return
        try:
            with open(arq, "rb") as f:
                bruto = f.read()
            self.png = imagens.remover_fundo_branco(bruto) if self.fundo.isChecked() else imagens.recortar_png(bruto)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Assinatura", f"Não foi possível usar esta imagem:\n{e}")
            return
        self._salvar(self.png)
        self.accept()


# --------------------------------------------------------------------------
class ListaArquivosDialog(QDialog):
    """Lista ordenável de arquivos (juntar PDFs, imagens -> PDF)."""

    def __init__(self, parent, titulo, filtro, texto_ok, checkbox=None, iniciais=None):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.filtro = filtro
        self.setMinimumSize(520, 380)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Arraste para reordenar ou use os botões. A ordem da lista será a ordem final."))
        self.lista = QListWidget()
        self.lista.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.lista.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        lay.addWidget(self.lista, 1)
        h = QHBoxLayout()
        for rot, fn in (("Adicionar…", self._add), ("Remover", self._rem), ("Subir", lambda: self._mover(-1)), ("Descer", lambda: self._mover(1))):
            b = QPushButton(rot)
            b.clicked.connect(fn)
            h.addWidget(b)
        lay.addLayout(h)
        self.chk = QCheckBox(checkbox) if checkbox else None
        if self.chk:
            self.chk.setChecked(True)
            lay.addWidget(self.chk)
        lay.addWidget(_botoes(self, texto_ok))
        for c in iniciais or []:
            self._inserir(c)

    def _inserir(self, caminho):
        it = QListWidgetItem(os.path.basename(caminho))
        it.setToolTip(caminho)
        it.setData(Qt.ItemDataRole.UserRole, caminho)
        self.lista.addItem(it)

    def _add(self):
        arqs, _ = QFileDialog.getOpenFileNames(self, "Adicionar arquivos", "", self.filtro)
        for a in arqs:
            self._inserir(a)

    def _rem(self):
        for it in self.lista.selectedItems():
            self.lista.takeItem(self.lista.row(it))

    def _mover(self, d):
        rows = sorted((self.lista.row(i) for i in self.lista.selectedItems()), reverse=(d > 0))
        for r in rows:
            n = r + d
            if 0 <= n < self.lista.count():
                it = self.lista.takeItem(r)
                self.lista.insertItem(n, it)
                it.setSelected(True)

    def caminhos(self):
        return [self.lista.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.lista.count())]

    def marcado(self):
        return bool(self.chk and self.chk.isChecked())


# --------------------------------------------------------------------------
class DividirDialog(QDialog):
    def __init__(self, parent, total):
        super().__init__(parent)
        self.setWindowTitle("Dividir PDF")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"O documento tem {total} página(s)."))
        self.r1 = QRadioButton("Por intervalos (um arquivo por intervalo):")
        self.r1.setChecked(True)
        self.iv = QLineEdit("1-" + str(max(1, total // 2)))
        self.iv.setPlaceholderText("ex.: 1-3, 5, 8-")
        self.r2 = QRadioButton("A cada N páginas:")
        self.n = QSpinBox()
        self.n.setRange(1, 10000)
        self.n.setValue(1)
        self.r3 = QRadioButton("Uma página por arquivo")
        for w in (self.r1, self.iv, self.r2, self.n, self.r3):
            lay.addWidget(w)
        lay.addWidget(QLabel("Salvar os arquivos na pasta:"))
        h, self.pasta = _linha_pasta(self)
        lay.addLayout(h)
        lay.addWidget(_botoes(self, "Dividir"))

    def valores(self):
        if self.r1.isChecked():
            return "intervalos", self.iv.text(), self.pasta.text()
        if self.r2.isChecked():
            return "cada_n", self.n.value(), self.pasta.text()
        return "uma_por_pagina", None, self.pasta.text()


class ComprimirDialog(QDialog):
    def __init__(self, parent, tamanho_atual: str):
        super().__init__(parent)
        self.setWindowTitle("Comprimir PDF")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Tamanho atual: {tamanho_atual}"))
        self.cb = QComboBox()
        self.cb.addItem("Leve — sem perda de qualidade (otimiza a estrutura)", "leve")
        self.cb.addItem("Médio — reduz imagens grandes (boa qualidade)", "medio")
        self.cb.addItem("Forte — menor tamanho (imagens com qualidade reduzida)", "forte")
        self.cb.setCurrentIndex(1)
        lay.addWidget(self.cb)
        lay.addWidget(_botoes(self, "Comprimir"))

    def nivel(self):
        return self.cb.currentData()


class ProtegerDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Proteger com senha")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Gera uma cópia protegida (criptografia AES-256). O arquivo aberto não é alterado."))
        form = QFormLayout()
        self.a1, self.a2, self.e1, self.e2 = (QLineEdit() for _ in range(4))
        for w in (self.a1, self.a2, self.e1, self.e2):
            w.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Senha para ABRIR:", self.a1)
        form.addRow("Confirmar senha de abrir:", self.a2)
        form.addRow("Senha para EDITAR:", self.e1)
        form.addRow("Confirmar senha de editar:", self.e2)
        lay.addLayout(form)
        self.imp = QCheckBox("Impedir impressão")
        self.cop = QCheckBox("Impedir cópia de texto")
        self.edi = QCheckBox("Impedir edição (exige senha de editar)")
        for w in (self.imp, self.cop, self.edi):
            lay.addWidget(w)
        lay.addWidget(QLabel("Deixe em branco a senha que não quiser usar."))
        lay.addWidget(_botoes(self, "Proteger e salvar…"))

    def accept(self):
        if self.a1.text() != self.a2.text() or self.e1.text() != self.e2.text():
            QMessageBox.warning(self, "Senha", "A confirmação não confere com a senha digitada.")
            return
        if not self.a1.text() and not self.e1.text():
            QMessageBox.warning(self, "Senha", "Informe ao menos uma senha.")
            return
        if (self.imp.isChecked() or self.cop.isChecked() or self.edi.isChecked()) and not self.e1.text():
            QMessageBox.warning(self, "Senha", "Para impor restrições, defina a senha de editar.")
            return
        super().accept()

    def valores(self):
        return dict(senha_abrir=self.a1.text(), senha_editar=self.e1.text(),
                    permitir_imprimir=not self.imp.isChecked(), permitir_copiar=not self.cop.isChecked(),
                    permitir_editar=not self.edi.isChecked())


class MarcaDaguaDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Marca d’água")
        self.setMinimumWidth(440)
        self.arquivo = ""
        lay = QVBoxLayout(self)
        self.rt = QRadioButton("Texto:")
        self.rt.setChecked(True)
        self.txt = QLineEdit("CONFIDENCIAL")
        self.ri = QRadioButton("Imagem:")
        self.lb = QLabel("(nenhuma)")
        bi = QPushButton("Escolher…")
        bi.clicked.connect(self._img)
        hi = QHBoxLayout()
        hi.addWidget(self.lb, 1)
        hi.addWidget(bi)
        for w in (self.rt, self.txt, self.ri):
            lay.addWidget(w)
        lay.addLayout(hi)
        form = QFormLayout()
        self.tam = QSpinBox()
        self.tam.setRange(8, 300)
        self.tam.setValue(70)
        self.op = QSpinBox()
        self.op.setRange(5, 100)
        self.op.setValue(25)
        self.op.setSuffix(" %")
        self.ang = QSpinBox()
        self.ang.setRange(-180, 180)
        self.ang.setValue(45)
        self.cor = BotaoCor("#808080")
        self.pag = QLineEdit()
        self.pag.setPlaceholderText("vazio = todas; ex.: 1-3, 5")
        form.addRow("Tamanho do texto:", self.tam)
        form.addRow("Opacidade:", self.op)
        form.addRow("Ângulo (texto):", self.ang)
        form.addRow("Cor (texto):", self.cor)
        form.addRow("Páginas:", self.pag)
        lay.addLayout(form)
        lay.addWidget(_botoes(self, "Aplicar"))

    def _img(self):
        a, _ = QFileDialog.getOpenFileName(self, "Imagem da marca d’água", "", "Imagens (*.png *.jpg *.jpeg)")
        if a:
            self.arquivo = a
            self.lb.setText(os.path.basename(a))
            self.ri.setChecked(True)

    def accept(self):
        if self.ri.isChecked() and not self.arquivo:
            QMessageBox.warning(self, "Marca d’água", "Escolha a imagem.")
            return
        if self.rt.isChecked() and not self.txt.text().strip():
            QMessageBox.warning(self, "Marca d’água", "Digite o texto.")
            return
        super().accept()

    def valores(self):
        return dict(tipo="imagem" if self.ri.isChecked() else "texto", texto=self.txt.text(), arquivo=self.arquivo,
                    tamanho=self.tam.value(), opacidade=self.op.value() / 100.0, angulo=self.ang.value(),
                    cor=self.cor.cor, paginas=self.pag.text())


class NumeracaoDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Numerar páginas")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.fmt = QLineEdit("Página {n} de {total}")
        self.pos = QComboBox()
        self.pos.addItems(POSICOES)
        self.ini = QSpinBox()
        self.ini.setRange(0, 100000)
        self.ini.setValue(1)
        self.tam = QSpinBox()
        self.tam.setRange(6, 48)
        self.tam.setValue(10)
        self.pag = QLineEdit()
        self.pag.setPlaceholderText("vazio = todas; ex.: 2-")
        form.addRow("Formato ({n} e {total}):", self.fmt)
        form.addRow("Posição:", self.pos)
        form.addRow("Começar em:", self.ini)
        form.addRow("Tamanho da fonte:", self.tam)
        form.addRow("Páginas:", self.pag)
        lay.addLayout(form)
        lay.addWidget(_botoes(self, "Aplicar"))

    def valores(self):
        return dict(formato=self.fmt.text(), posicao=self.pos.currentIndex(), inicio=self.ini.value(),
                    tamanho=self.tam.value(), paginas=self.pag.text())


class FormularioDialog(QDialog):
    def __init__(self, parent, campos):
        super().__init__(parent)
        self.setWindowTitle("Preencher formulário")
        self.setMinimumSize(480, 420)
        self.campos = campos
        self.widgets = {}
        lay = QVBoxLayout(self)
        area = QScrollArea()
        area.setWidgetResizable(True)
        corpo = QWidget()
        form = QFormLayout(corpo)
        for c in campos:
            if c["tipo"] == "texto":
                w = QLineEdit("" if c["valor"] in ("None",) else c["valor"])
            elif c["tipo"] == "caixa":
                w = QCheckBox()
                w.setChecked(c["valor"] not in ("", "/Off", "None"))
            else:
                w = QComboBox()
                w.setEditable(c["tipo"] == "lista")
                w.addItems([o.lstrip("/") for o in c["opcoes"]])
                if c["valor"]:
                    w.setCurrentText(c["valor"].lstrip("/"))
            self.widgets[c["nome"]] = w
            form.addRow(c["nome"] + ":", w)
        area.setWidget(corpo)
        lay.addWidget(area, 1)
        self.achatar = QCheckBox("Achatar o formulário (transformar os campos em conteúdo fixo, sem poder editar depois)")
        lay.addWidget(self.achatar)
        lay.addWidget(_botoes(self, "Aplicar"))

    def valores(self):
        out = {}
        for c in self.campos:
            w = self.widgets[c["nome"]]
            if c["tipo"] == "texto":
                out[c["nome"]] = w.text()
            elif c["tipo"] == "caixa":
                estado = (c["opcoes"] or ["/Yes"])[0]
                out[c["nome"]] = estado if w.isChecked() else "/Off"
            elif c["tipo"] == "radio":
                out[c["nome"]] = "/" + w.currentText()
            else:
                out[c["nome"]] = w.currentText()
        return out, self.achatar.isChecked()


class PdfParaImagensDialog(QDialog):
    def __init__(self, parent, total):
        super().__init__(parent)
        self.setWindowTitle("Converter PDF em imagens")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.dpi = QComboBox()
        for d in (72, 96, 150, 200, 300, 600):
            self.dpi.addItem(f"{d} DPI", d)
        self.dpi.setCurrentIndex(2)
        self.fmt = QComboBox()
        self.fmt.addItem("PNG (sem perdas)", "png")
        self.fmt.addItem("JPG (menor)", "jpg")
        self.pag = QLineEdit()
        self.pag.setPlaceholderText(f"vazio = todas as {total}; ex.: 1-3, 5")
        form.addRow("Resolução:", self.dpi)
        form.addRow("Formato:", self.fmt)
        form.addRow("Páginas:", self.pag)
        lay.addLayout(form)
        lay.addWidget(QLabel("Salvar na pasta:"))
        h, self.pasta = _linha_pasta(self)
        lay.addLayout(h)
        lay.addWidget(_botoes(self, "Converter"))

    def valores(self):
        return self.dpi.currentData(), self.fmt.currentData(), self.pag.text(), self.pasta.text()
