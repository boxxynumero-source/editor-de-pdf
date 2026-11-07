"""Janela principal do Editor de PDF."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QObject, QRunnable, QSettings, QSize, Qt, QTimer, Signal, QItemSelectionModel
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (QApplication, QColorDialog, QDockWidget, QDoubleSpinBox, QFileDialog, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QProgressDialog, QSpinBox, QToolBar, QAbstractItemView)

from .. import __version__
from ..core import imagens, overlay, pdfops
from ..core.model import Item
from . import dialogs
from .document import Documento
from .tasks import Tarefa, aplicar_tema, pasta_dados
from .viewer import PdfVista

FERRAMENTAS = [
    # chave, rótulo, glifo, dica, flags
    ("selecionar", "Selecionar", "↖", "Selecionar, mover e redimensionar itens (duplo clique edita texto; Delete exclui)", ""),
    ("texto", "Texto", "T", "Clique na página para adicionar texto", ""),
    ("imagem", "Imagem", "▣", "Clique na página para inserir uma imagem PNG/JPG", ""),
    ("assinatura", "Assinatura", "✍", "Clique na página para inserir uma assinatura (desenhada ou importada)", ""),
    ("realce", "Realçar", "▬", "Arraste sobre o trecho para marcar com marca-texto", ""),
    ("sublinhar", "Sublinhar", "U", "Arraste sobre o trecho para sublinhar", "u"),
    ("riscar", "Riscar", "S", "Arraste sobre o trecho para riscar", "s"),
    ("caneta", "Desenho", "✎", "Desenho livre com o mouse", ""),
    ("retangulo", "Retângulo", "▭", "Arraste para desenhar um retângulo", ""),
    ("circulo", "Círculo", "◯", "Arraste para desenhar um círculo/elipse", ""),
    ("seta", "Seta", "➜", "Arraste para desenhar uma seta", ""),
    ("nota", "Nota", "▤", "Clique para adicionar uma nota adesiva", ""),
    ("tarja", "Tarja preta", "■", "Arraste sobre o que deve ser apagado de verdade (redação). A página será rasterizada ao aplicar.", ""),
    ("editar_texto", "Editar texto", "Aa", "Arraste sobre um texto existente: ele é coberto e você escreve o novo texto por cima", ""),
]
DICAS_STATUS = {
    "editar_texto": "Editar texto existente: arraste sobre o trecho; ele será COBERTO e o novo texto vai por cima. O texto original continua no arquivo, a menos que você marque “remover de verdade”.",
    "tarja": "Tarja: arraste sobre o conteúdo. Ao salvar, a página inteira vira imagem e o conteúdo coberto deixa de existir no arquivo.",
}


def formatar_tamanho(n: int) -> str:
    for un in ("B", "KB", "MB", "GB"):
        if n < 1024 or un == "GB":
            return f"{n:.0f} {un}" if un == "B" else f"{n:.1f} {un}"
        n /= 1024.0


def _icone(glifo: str, flags: str = "") -> QIcon:
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    f = QFont("Segoe UI Symbol", 14)
    f.setBold(True)
    f.setUnderline("u" in flags)
    f.setStrikeOut("s" in flags)
    p.setFont(f)
    p.setPen(QApplication.palette().color(QPalette.ColorRole.ButtonText))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, glifo)
    p.end()
    return QIcon(pm)


class _SinaisMini(QObject):
    pronta = Signal(int, object, int)


class _MiniTarefa(QRunnable):
    def __init__(self, vista: PdfVista, tamanhos, versao):
        super().__init__()
        self.vista, self.tamanhos, self.versao = vista, tamanhos, versao
        self.sinais = _SinaisMini()
        self.setAutoDelete(False)

    def run(self):
        for i, (pw, ph) in enumerate(self.tamanhos):
            if self.vista._versao != self.versao:
                return
            try:
                img = self.vista.renderizador.renderizar(i, min(112 / pw, 150 / ph))
            except Exception:  # noqa: BLE001
                return
            if img is not None:
                self.sinais.pronta.emit(i, img, self.versao)


class Miniaturas(QListWidget):
    reordenado = Signal(list)
    pagina_escolhida = Signal(int)

    def __init__(self):
        super().__init__()
        self.setIconSize(QSize(112, 150))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSpacing(6)
        self.setUniformItemSizes(False)
        self._ignorar = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._emitir)
        self.model().rowsMoved.connect(lambda *a: None if self._ignorar else self._timer.start())
        self.itemClicked.connect(lambda it: self.pagina_escolhida.emit(self.row(it)))

    def _emitir(self):
        self.reordenado.emit([self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())])

    def preencher(self, n: int):
        self._ignorar = True
        self.clear()
        for i in range(n):
            it = QListWidgetItem(str(i + 1))
            it.setData(Qt.ItemDataRole.UserRole, i)
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.addItem(it)
        self._ignorar = False

    def definir_icone(self, i: int, img: QImage):
        if i < self.count():
            self.item(i).setIcon(QIcon(QPixmap.fromImage(img)))

    def indices_selecionados(self):
        return sorted(self.row(i) for i in self.selectedItems())


class JanelaPrincipal(QMainWindow):
    def __init__(self, arquivo_inicial: str | None = None):
        super().__init__()
        self.cfg = QSettings("EditorDePDF", "EditorDePDF")
        self.doc: Documento | None = None
        self._ocupado = False
        self._tarefas: set = set()
        self._confirmou_sobrescrever = False
        self._ultima_fonte = dict(font="Helvetica", size=14.0, color="#000000", bold=False, italic=False)
        self._icones: list = []
        self._acoes_doc: list[QAction] = []
        self.resize(1280, 860)
        self.setAcceptDrops(True)

        self.vista = PdfVista()
        self.setCentralWidget(self.vista)
        self.miniaturas = Miniaturas()
        dock = QDockWidget("Páginas", self)
        dock.setWidget(self.miniaturas)
        dock.setMinimumWidth(150)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self._dock = dock
        self.miniaturas.reordenado.connect(self._reordenar)
        self.miniaturas.pagina_escolhida.connect(lambda i: self.vista.ir_para(i))
        self.miniaturas.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.miniaturas.customContextMenuRequested.connect(self._menu_miniaturas)

        self.vista.pagina_mudou.connect(self._pagina_mudou)
        self.vista.zoom_mudou.connect(lambda z: self.lb_zoom.setText(f"{z * 100:.0f}%"))
        self.vista.pedido_criar.connect(self._pedido_criar)
        self.vista.pedido_editar.connect(self._editar_texto_item)

        self._criar_acoes()
        self._criar_menus()
        self._criar_barras()
        self._criar_status()
        self._aplicar_icones()
        self._atualizar_estado()
        if arquivo_inicial:
            QTimer.singleShot(50, lambda: self._abrir_caminho(arquivo_inicial))

    # ------------------------------------------------------------------
    # Construção da interface
    # ------------------------------------------------------------------
    def _acao(self, texto, slot=None, atalho=None, dica=None, precisa_doc=True, checkable=False):
        a = QAction(texto, self)
        if slot:
            a.triggered.connect(lambda _=False, s=slot: s())
        if atalho:
            a.setShortcut(atalho if isinstance(atalho, QKeySequence) else QKeySequence(atalho))
        if dica:
            a.setToolTip(dica)
            a.setStatusTip(dica)
        a.setCheckable(checkable)
        if precisa_doc:
            self._acoes_doc.append(a)
        return a

    def _criar_acoes(self):
        A = self._acao
        self.a_abrir = A("Abrir…", self.abrir, QKeySequence.StandardKey.Open, "Abrir um PDF (Ctrl+O)", precisa_doc=False)
        self.a_salvar = A("Salvar", self.salvar, QKeySequence.StandardKey.Save, "Salvar (Ctrl+S)")
        self.a_salvar_como = A("Salvar como…", self.salvar_como, QKeySequence("Ctrl+Shift+S"), "Salvar uma cópia")
        self.a_fechar = A("Fechar documento", self.fechar_documento, QKeySequence("Ctrl+W"))
        self.a_sair = A("Sair", self.close, QKeySequence("Ctrl+Q"), precisa_doc=False)
        self.a_desfazer = A("Desfazer", lambda: self.doc and self.doc.desfazer(), QKeySequence.StandardKey.Undo, "Desfazer (Ctrl+Z)")
        self.a_refazer = A("Refazer", lambda: self.doc and self.doc.refazer(), QKeySequence("Ctrl+Y"), "Refazer (Ctrl+Y)")
        self.a_excluir_sel = A("Excluir item selecionado", lambda: self.vista.excluir_selecao(), None, "Remove o item selecionado (Delete)")
        self.a_zoom_mais = A("Zoom +", lambda: self.vista.definir_zoom(self.vista.zoom * 1.2), QKeySequence("Ctrl+="), "Aumentar zoom (Ctrl + roda do mouse)")
        self.a_zoom_menos = A("Zoom −", lambda: self.vista.definir_zoom(self.vista.zoom / 1.2), QKeySequence("Ctrl+-"), "Diminuir zoom")
        self.a_largura = A("Ajustar à largura", self.vista.ajustar_largura, QKeySequence("Ctrl+0"))
        self.a_pagina = A("Ajustar à página", self.vista.ajustar_pagina, QKeySequence("Ctrl+1"))
        self.a_ir = A("Ir para a página…", self.ir_para_pagina, QKeySequence("Ctrl+G"))
        self.a_tema = A("Tema escuro", self.alternar_tema, None, precisa_doc=False, checkable=True)
        self.a_tema.setChecked(self.cfg.value("escuro", False, type=bool))
        self.a_cor = A("Cor…", self.escolher_cor, None, "Cor das anotações e desenhos", precisa_doc=False)
        self.a_cor_realce = A("Cor do marca-texto…", self.escolher_cor_realce, None, precisa_doc=False)

        self.a_girar_d = A("Girar à direita", lambda: self.girar(90), QKeySequence("Ctrl+R"), "Girar páginas selecionadas 90° (Ctrl+R)")
        self.a_girar_e = A("Girar à esquerda", lambda: self.girar(-90), QKeySequence("Ctrl+Shift+R"))
        self.a_excluir_pag = A("Excluir páginas", self.excluir_paginas, QKeySequence("Ctrl+Del"))
        self.a_duplicar = A("Duplicar páginas", self.duplicar_paginas)
        self.a_branco = A("Inserir página em branco", self.inserir_branco)
        self.a_extrair = A("Extrair páginas para novo PDF…", self.extrair_paginas)

        self.a_juntar = A("Juntar PDFs…", self.juntar, None, precisa_doc=False)
        self.a_dividir = A("Dividir PDF…", self.dividir)
        self.a_comprimir = A("Comprimir PDF…", self.comprimir)
        self.a_proteger = A("Proteger com senha…", self.proteger)
        self.a_remover_senha = A("Remover senha", self.remover_senha)
        self.a_marca = A("Marca d’água…", self.marca_dagua)
        self.a_numerar = A("Numerar páginas…", self.numerar)
        self.a_form = A("Preencher formulário…", self.preencher_formulario)
        self.a_achatar = A("Achatar formulário", self.achatar_formulario)
        self.a_img2pdf = A("Imagens para PDF…", self.imagens_para_pdf, None, precisa_doc=False)
        self.a_pdf2img = A("PDF para imagens…", self.pdf_para_imagens)
        self.a_sobre = A("Sobre", self.sobre, None, precisa_doc=False)

        self.grupo_ferr = QActionGroup(self)
        self.grupo_ferr.setExclusive(True)
        self.acoes_ferr: dict[str, QAction] = {}
        teclas = {"selecionar": "V", "texto": "T"}
        for chave, rot, glifo, dica, flags in FERRAMENTAS:
            a = self._acao(rot, None, teclas.get(chave), dica, checkable=True)
            a.triggered.connect(lambda _=False, c=chave: self.escolher_ferramenta(c))
            self.grupo_ferr.addAction(a)
            self.acoes_ferr[chave] = a
            self._icones.append((a, glifo, flags))
        self.acoes_ferr["selecionar"].setChecked(True)

        for a, g in ((self.a_abrir, "↥"), (self.a_salvar, "↧"), (self.a_desfazer, "↶"), (self.a_refazer, "↷"),
                     (self.a_zoom_mais, "+"), (self.a_zoom_menos, "−"), (self.a_largura, "↔"), (self.a_pagina, "▯"),
                     (self.a_girar_d, "↻"), (self.a_girar_e, "↺"), (self.a_excluir_pag, "✖"), (self.a_duplicar, "⧉"),
                     (self.a_branco, "＋"), (self.a_cor, "●")):
            self._icones.append((a, g, ""))

    def _criar_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&Arquivo")
        for a in (self.a_abrir, self.a_salvar, self.a_salvar_como, None, self.a_fechar, None, self.a_sair):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("&Editar")
        for a in (self.a_desfazer, self.a_refazer, None, self.a_excluir_sel, None, self.a_cor, self.a_cor_realce):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("E&xibir")
        for a in (self.a_zoom_mais, self.a_zoom_menos, self.a_largura, self.a_pagina, None, self.a_ir, None, self.a_tema):
            m.addSeparator() if a is None else m.addAction(a)
        m.addAction(self._dock.toggleViewAction())
        m = mb.addMenu("&Páginas")
        for a in (self.a_girar_d, self.a_girar_e, self.a_excluir_pag, self.a_duplicar, self.a_branco, self.a_extrair):
            m.addAction(a)
        m = mb.addMenu("&Ferramentas")
        for a in (self.a_juntar, self.a_dividir, None, self.a_comprimir, None, self.a_proteger, self.a_remover_senha, None,
                  self.a_marca, self.a_numerar, None, self.a_form, self.a_achatar, None, self.a_img2pdf, self.a_pdf2img):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("A&nexar")
        for chave, *_ in FERRAMENTAS:
            m.addAction(self.acoes_ferr[chave])
        m = mb.addMenu("A&juda")
        m.addAction(self.a_sobre)

    def _criar_barras(self):
        tb = QToolBar("Principal")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        tb.setIconSize(QSize(24, 24))
        self.addToolBar(tb)
        for a in (self.a_abrir, self.a_salvar, None, self.a_desfazer, self.a_refazer, None, self.a_girar_e, self.a_girar_d,
                  self.a_duplicar, self.a_branco, self.a_excluir_pag, None, self.a_zoom_menos, self.a_zoom_mais,
                  self.a_largura, self.a_pagina):
            tb.addSeparator() if a is None else tb.addAction(a)
        tb.addSeparator()
        tb.addWidget(QLabel(" Página "))
        self.sp_pag = QSpinBox()
        self.sp_pag.setRange(1, 1)
        self.sp_pag.valueChanged.connect(lambda v: self.vista.ir_para(v - 1))
        tb.addWidget(self.sp_pag)
        self.lb_total = QLabel(" de 0 ")
        tb.addWidget(self.lb_total)
        self.lb_zoom = QLabel("100%")
        tb.addWidget(self.lb_zoom)

        self.addToolBarBreak()
        tf = QToolBar("Ferramentas de edição")
        tf.setMovable(False)
        tf.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        tf.setIconSize(QSize(22, 22))
        self.addToolBar(tf)
        for chave, *_ in FERRAMENTAS:
            tf.addAction(self.acoes_ferr[chave])
        tf.addSeparator()
        tf.addAction(self.a_cor)
        tf.addWidget(QLabel(" Espessura "))
        self.sp_esp = QDoubleSpinBox()
        self.sp_esp.setRange(0.5, 20)
        self.sp_esp.setSingleStep(0.5)
        self.sp_esp.setValue(self.vista.espessura)
        self.sp_esp.valueChanged.connect(lambda v: setattr(self.vista, "espessura", v))
        tf.addWidget(self.sp_esp)

    def _criar_status(self):
        self.lb_status = QLabel("")
        self.statusBar().addPermanentWidget(self.lb_status, 1)
        self.statusBar().showMessage("Abra um PDF (Ctrl+O) ou arraste um arquivo para esta janela.")

    def _aplicar_icones(self):
        for a, g, f in self._icones:
            a.setIcon(_icone(g, f))

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def rodar(self, job, ao_concluir, rotulo="Processando…", progresso=False, ao_erro=None):
        if self._ocupado:
            return
        self._ocupado = True
        dlg = QProgressDialog(rotulo, "", 0, 0, self)
        dlg.setWindowTitle("Aguarde")
        dlg.setCancelButton(None)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(250)
        t = Tarefa(job, com_progresso=progresso)
        self._tarefas.add(t)

        def encerrar():
            dlg.close()
            dlg.deleteLater()
            self._ocupado = False
            self._tarefas.discard(t)

        def ok(r):
            encerrar()
            try:
                ao_concluir(r)
            except Exception as e:  # noqa: BLE001
                self._erro(e)

        def falha(e):
            encerrar()
            (ao_erro or self._erro)(e)

        def prog(i, n):
            dlg.setMaximum(max(n, 1))
            dlg.setValue(min(i, n))

        t.sinais.concluido.connect(ok)
        t.sinais.erro.connect(falha)
        if progresso:
            t.sinais.progresso.connect(prog)
        QThreadPool_global().start(t)

    def _erro(self, e):
        import logging
        logging.error("Erro mostrado ao usuário: %r", e)
        if isinstance(e, pdfops.PdfError) or isinstance(e, ValueError):
            QMessageBox.warning(self, "Não foi possível concluir", str(e))
        elif isinstance(e, PermissionError):
            QMessageBox.warning(self, "Arquivo em uso", "O arquivo está em uso por outro programa ou sem permissão de acesso.")
        elif isinstance(e, MemoryError):
            QMessageBox.critical(self, "Memória insuficiente", "O arquivo é grande demais para esta operação.")
        else:
            QMessageBox.critical(self, "Erro inesperado",
                                 f"Ocorreu um erro inesperado:\n{e}\n\nOs detalhes foram gravados em:\n{os.path.join(pasta_dados(), 'erros.log')}")

    def _operacao(self, funcao, rotulo="Processando…", apos=None):
        """Aplica `funcao(bytes)->bytes` ao documento (com desfazer)."""
        if not self.doc:
            return
        snap, job = self.doc.preparar(funcao)

        def pronto(novos):
            self.doc.confirmar(snap, novos)
            if apos:
                apos(novos)

        self.rodar(job, pronto, rotulo)

    def _gravar_copia(self, funcao, titulo, nome_sugerido, apos=None):
        """Gera uma cópia (sem alterar o documento aberto) e pede onde salvar."""
        if not self.doc:
            return
        destino, _ = QFileDialog.getSaveFileName(self, titulo, self._pasta_base(nome_sugerido), "PDF (*.pdf)")
        if not destino:
            return
        if not destino.lower().endswith(".pdf"):
            destino += ".pdf"
        _snap, job = self.doc.preparar(funcao)

        def tudo():
            dados = job()
            pdfops.escrever_atomico(destino, dados)
            return dados

        self.rodar(tudo, lambda d: (self.statusBar().showMessage(f"Arquivo salvo: {destino}", 8000), apos(destino, d) if apos else None), "Gravando…")

    def _pasta_base(self, nome):
        base = os.path.dirname(self.doc.caminho) if self.doc and self.doc.caminho else self.cfg.value("pasta", os.path.expanduser("~"))
        return os.path.join(base, nome)

    def _nome_base(self):
        return os.path.splitext(os.path.basename(self.doc.caminho))[0] if self.doc and self.doc.caminho else "documento"

    def _paginas_selecionadas(self):
        sel = self.miniaturas.indices_selecionados()
        return sel or [self.vista.pagina_atual()]

    @staticmethod
    def _caminho_livre(caminho):
        if not os.path.exists(caminho):
            return caminho
        base, ext = os.path.splitext(caminho)
        n = 1
        while os.path.exists(f"{base} ({n}){ext}"):
            n += 1
        return f"{base} ({n}){ext}"

    # ------------------------------------------------------------------
    # Abrir / salvar
    # ------------------------------------------------------------------
    def abrir(self):
        arq, _ = QFileDialog.getOpenFileName(self, "Abrir PDF", self.cfg.value("pasta", ""), "Arquivos PDF (*.pdf);;Todos os arquivos (*)")
        if arq:
            self._abrir_caminho(arq)

    def _abrir_caminho(self, caminho):
        self._com_confirmacao(lambda: self._abrir_sem_confirmar(caminho))

    def _abrir_sem_confirmar(self, caminho):
        try:
            bruto = pdfops.ler_arquivo(caminho)
        except pdfops.PdfError as e:
            self._erro(e)
            return
        self._tentar_abrir(caminho, bruto, "")

    def _tentar_abrir(self, caminho, bruto, senha):
        def falha(e):
            if isinstance(e, (pdfops.SenhaNecessaria, pdfops.SenhaIncorreta)):
                msg = "Este PDF é protegido por senha.\nDigite a senha:" if isinstance(e, pdfops.SenhaNecessaria) else "Senha incorreta. Tente novamente:"
                txt, ok = QInputDialog.getText(self, "PDF protegido", msg, QLineEdit.EchoMode.Password)
                if ok:
                    self._tentar_abrir(caminho, bruto, txt)
            else:
                self._erro(e)

        def pronto(dados):
            self.cfg.setValue("pasta", os.path.dirname(caminho))
            self._definir_documento(Documento(dados, caminho, senha))

        self.rodar(lambda: pdfops.normalizar(bruto, senha), pronto, "Abrindo o arquivo…", ao_erro=falha)

    def _definir_documento(self, doc: Documento | None):
        self.doc = doc
        self._confirmou_sobrescrever = False
        self.vista.set_documento(doc)
        if doc:
            doc.estado_mudou.connect(self._atualizar_estado)
            doc.estrutura_mudou.connect(self._estrutura_mudou)
            self._estrutura_mudou()
        else:
            self.miniaturas.preencher(0)
        self._atualizar_estado()

    def _estrutura_mudou(self):
        n = self.doc.num_paginas
        self.miniaturas.preencher(n)
        self.sp_pag.blockSignals(True)
        self.sp_pag.setRange(1, max(1, n))
        self.sp_pag.blockSignals(False)
        self.lb_total.setText(f" de {n} ")
        tarefa = _MiniTarefa(self.vista, list(self.vista._tamanhos), self.vista._versao)
        tarefa.sinais.pronta.connect(self._miniatura_pronta)
        self._mini_ref = tarefa
        self._pool_mini().start(tarefa)

    def _miniatura_pronta(self, i, img, versao):
        if versao == self.vista._versao:
            self.miniaturas.definir_icone(i, img)

    def _pool_mini(self):
        if not hasattr(self, "_pm"):
            from PySide6.QtCore import QThreadPool
            self._pm = QThreadPool()
            self._pm.setMaxThreadCount(1)
        return self._pm

    def _pagina_mudou(self, i):
        self.sp_pag.blockSignals(True)
        self.sp_pag.setValue(i + 1)
        self.sp_pag.blockSignals(False)
        if i < self.miniaturas.count():
            self.miniaturas.setCurrentRow(i, QItemSelectionModel.SelectionFlag.NoUpdate)
            self.miniaturas.scrollToItem(self.miniaturas.item(i))

    def _atualizar_estado(self):
        d = self.doc
        for a in self._acoes_doc:
            a.setEnabled(d is not None)
        if d is not None:
            self.a_desfazer.setEnabled(d.pode_desfazer())
            self.a_refazer.setEnabled(d.pode_refazer())
            nome = os.path.basename(d.caminho) if d.caminho else "Sem título"
            self.setWindowTitle(f"{'● ' if d.sujo else ''}{nome} — Editor de PDF")
        else:
            self.setWindowTitle("Editor de PDF")

    def salvar(self, depois=None):
        if not self.doc:
            return
        if not self.doc.caminho:
            return self.salvar_como(depois)
        if not self._confirmou_sobrescrever:
            r = QMessageBox.question(self, "Salvar", f"Isto substituirá o arquivo original:\n{self.doc.caminho}\n\nDeseja continuar?\n(Use “Salvar como…” para manter o original.)",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return
            self._confirmou_sobrescrever = True
        self._gravar(self.doc.caminho, depois)

    def salvar_como(self, depois=None):
        if not self.doc:
            return
        sugestao = self._caminho_livre(self._pasta_base(self._nome_base() + "_editado.pdf"))
        destino, _ = QFileDialog.getSaveFileName(self, "Salvar como", sugestao, "PDF (*.pdf)")
        if not destino:
            return
        if not destino.lower().endswith(".pdf"):
            destino += ".pdf"
        self._confirmou_sobrescrever = True  # o próprio diálogo já confirmou a substituição
        self._gravar(destino, depois)

    def _gravar(self, caminho, depois=None):
        job_dados = self.doc.preparar_salvar()

        def tudo():
            d = job_dados()
            pdfops.escrever_atomico(caminho, d)
            return d

        def pronto(_d):
            self.doc.marcar_salvo(caminho)
            self.statusBar().showMessage(f"Salvo em {caminho}", 8000)
            if depois:
                depois()

        self.rodar(tudo, pronto, "Salvando…")

    def _com_confirmacao(self, depois):
        """Executa `depois()` se não há alterações pendentes, ou após o usuário
        salvar/descartar. “Cancelar” não faz nada."""
        if not self.doc or not self.doc.sujo:
            depois()
            return
        m = QMessageBox(self)
        m.setWindowTitle("Alterações não salvas")
        m.setText("Há alterações não salvas. O que deseja fazer?")
        bs = m.addButton("Salvar", QMessageBox.ButtonRole.AcceptRole)
        bd = m.addButton("Descartar", QMessageBox.ButtonRole.DestructiveRole)
        m.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        m.exec()
        if m.clickedButton() is bd:
            self.doc.sujo = False
            depois()
        elif m.clickedButton() is bs:
            self.salvar(depois)

    def fechar_documento(self):
        self._com_confirmacao(lambda: self._definir_documento(None))

    def closeEvent(self, e):
        if self._ocupado:
            e.ignore()
            return
        if self.doc and self.doc.sujo:
            e.ignore()
            self._com_confirmacao(self.close)
        else:
            e.accept()

    # arrastar e soltar
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(".pdf") for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.toLocalFile().lower().endswith(".pdf"):
                self._abrir_caminho(u.toLocalFile())
                break

    # ------------------------------------------------------------------
    # Exibição e ferramentas
    # ------------------------------------------------------------------
    def ir_para_pagina(self):
        if not self.doc:
            return
        n, ok = QInputDialog.getInt(self, "Ir para a página", f"Página (1 a {self.doc.num_paginas}):",
                                    self.vista.pagina_atual() + 1, 1, self.doc.num_paginas)
        if ok:
            self.vista.ir_para(n - 1)

    def escolher_ferramenta(self, chave):
        self.vista.ferramenta = chave
        self.lb_status.setText(DICAS_STATUS.get(chave, ""))

    def escolher_cor(self):
        c = QColorDialog.getColor(QColor(self.vista.cor), self, "Cor das anotações")
        if c.isValid():
            self.vista.cor = c.name()

    def escolher_cor_realce(self):
        c = QColorDialog.getColor(QColor(self.vista.cor_realce), self, "Cor do marca-texto")
        if c.isValid():
            self.vista.cor_realce = c.name()

    def alternar_tema(self):
        escuro = self.a_tema.isChecked()
        self.cfg.setValue("escuro", escuro)
        aplicar_tema(QApplication.instance(), escuro)
        self._aplicar_icones()

    # ------------------------------------------------------------------
    # Criação de itens (texto, imagem, assinatura, notas, edição de texto)
    # ------------------------------------------------------------------
    def _pedido_criar(self, ferr, pag, x, y, w, h):
        doc = self.doc
        if not doc:
            return
        if ferr == "texto":
            u = self._ultima_fonte
            d = dialogs.TextoDialog(self, "Adicionar texto", familia=u["font"], tamanho=u["size"], cor=u["color"], negrito=u["bold"], italico=u["italic"])
            if d.exec():
                v = d.valores()
                if v["text"].strip():
                    self._ultima_fonte = {k: v[k] for k in ("font", "size", "color", "bold", "italic")}
                    it = Item("text", pag, x, y, color=v["color"], text=v["text"], font=v["font"], size=v["size"], bold=v["bold"], italic=v["italic"])
                    doc.adicionar_item(it)
                    self.vista.selecionar(it)
        elif ferr == "nota":
            d = dialogs.TextoDialog(self, "Nota", so_texto=True)
            if d.exec() and d.valores()["text"].strip():
                it = Item("note", pag, x, y, color="#333333", fill="#FFF59D", text=d.valores()["text"], size=11)
                doc.adicionar_item(it)
                self.vista.selecionar(it)
        elif ferr in ("imagem", "assinatura"):
            if ferr == "imagem":
                arq, _ = QFileDialog.getOpenFileName(self, "Inserir imagem", self.cfg.value("pasta", ""), "Imagens (*.png *.jpg *.jpeg)")
                if not arq:
                    return
                try:
                    with open(arq, "rb") as f:
                        dados = f.read()
                except OSError as e:
                    self._erro(e)
                    return
                largura_max = 220.0
            else:
                d = dialogs.AssinaturaDialog(self)
                if not d.exec() or not d.png:
                    return
                dados, largura_max = d.png, 150.0
            img = QImage.fromData(dados)
            if img.isNull():
                QMessageBox.warning(self, "Imagem", "Não foi possível ler esta imagem.")
                return
            w0 = min(largura_max, img.width() * 0.75)
            it = Item("image", pag, x, y, w0, w0 * img.height() / img.width(), image=dados)
            doc.adicionar_item(it)
            self.vista.selecionar(it)
        elif ferr == "editar_texto":
            try:
                existente = pdfops.texto_na_area(doc.dados, pag, x, y, w, h)
            except Exception:  # noqa: BLE001
                existente = ""
            aviso = ("O trecho selecionado será COBERTO por um retângulo branco e o novo texto escrito por cima. "
                     "Isto não é uma edição perfeita do texto original (fonte, espaçamento e alinhamento podem diferir).")
            d = dialogs.TextoDialog(self, "Editar texto existente", texto=existente, tamanho=round(max(6.0, h * 0.8), 1), aviso=aviso,
                                    opcao="Remover o texto original de verdade (a página vira imagem; o texto deixa de ser selecionável)")
            if d.exec():
                v = d.valores()
                cobertura = Item("tarja", pag, x, y, w, h, color="#FFFFFF") if v["remover"] else Item("rect", pag, x, y, w, h, color="#FFFFFF", fill="#FFFFFF", width=0)
                novos = [cobertura]
                if v["text"].strip():
                    novos.append(Item("text", pag, x, y + max(0.0, (h - v["size"] * 1.2) / 2), color=v["color"], text=v["text"], font=v["font"],
                                      size=v["size"], bold=v["bold"], italic=v["italic"]))
                doc.adicionar_itens(novos)
                self.vista.selecionar(novos[-1])

    def _editar_texto_item(self, it: Item):
        d = dialogs.TextoDialog(self, "Editar texto", texto=it.text, familia=it.font, tamanho=it.size, cor=it.color,
                                negrito=it.bold, italico=it.italic, so_texto=(it.kind == "note"))
        if d.exec():
            v = d.valores()
            self.doc.registrar()
            it.text = v["text"] or it.text
            if it.kind == "text":
                it.font, it.size, it.color, it.bold, it.italic = v["font"], v["size"], v["color"], v["bold"], v["italic"]
            self.doc.itens_mudaram.emit()

    # ------------------------------------------------------------------
    # Páginas
    # ------------------------------------------------------------------
    def _menu_miniaturas(self, pos):
        if not self.doc:
            return
        m = QMenu(self)
        for a in (self.a_girar_e, self.a_girar_d, self.a_duplicar, self.a_branco, self.a_excluir_pag, self.a_extrair):
            m.addAction(a)
        m.exec(self.miniaturas.mapToGlobal(pos))

    def _reordenar(self, ordem):
        if not self.doc or ordem == list(range(self.doc.num_paginas)):
            return
        self._operacao(lambda d: pdfops.reordenar(d, ordem), "Reordenando páginas…")

    def girar(self, graus):
        sel = self._paginas_selecionadas()
        self._operacao(lambda d: pdfops.girar(d, sel, graus), "Girando páginas…")

    def excluir_paginas(self):
        sel = self._paginas_selecionadas()
        if len(sel) >= self.doc.num_paginas:
            QMessageBox.information(self, "Excluir páginas", "Não é possível excluir todas as páginas do documento.")
            return
        if QMessageBox.question(self, "Excluir páginas", f"Excluir {len(sel)} página(s)? (Você pode desfazer com Ctrl+Z.)") != QMessageBox.StandardButton.Yes:
            return
        self._operacao(lambda d: pdfops.excluir(d, sel), "Excluindo páginas…")

    def duplicar_paginas(self):
        sel = self._paginas_selecionadas()
        self._operacao(lambda d: pdfops.duplicar(d, sel), "Duplicando páginas…")

    def inserir_branco(self):
        pos = max(self._paginas_selecionadas()) + 1
        self._operacao(lambda d: pdfops.inserir_em_branco(d, pos), "Inserindo página em branco…")

    def extrair_paginas(self):
        sel = self._paginas_selecionadas()
        self._gravar_copia(lambda d: pdfops.extrair(d, sel), "Extrair páginas", f"{self._nome_base()}_extraido.pdf")

    # ------------------------------------------------------------------
    # Juntar / dividir / comprimir / senha
    # ------------------------------------------------------------------
    def juntar(self):
        ini = [self.doc.caminho] if self.doc and self.doc.caminho and not self.doc.sujo else []
        d = dialogs.ListaArquivosDialog(self, "Juntar PDFs", "Arquivos PDF (*.pdf)", "Juntar…", iniciais=ini)
        if not d.exec():
            return
        caminhos = d.caminhos()
        if len(caminhos) < 2:
            QMessageBox.information(self, "Juntar PDFs", "Escolha pelo menos dois arquivos.")
            return
        lidos = []
        for c in caminhos:
            try:
                bruto = pdfops.ler_arquivo(c)
            except pdfops.PdfError as e:
                self._erro(e)
                return
            senha = ""
            while True:
                try:
                    pdfops.abrir(bruto, senha).close()
                    break
                except pdfops.PdfError as e:
                    if isinstance(e, (pdfops.SenhaNecessaria, pdfops.SenhaIncorreta)):
                        txt, ok = QInputDialog.getText(self, "PDF protegido", f"Senha de “{os.path.basename(c)}”:", QLineEdit.EchoMode.Password)
                        if not ok:
                            return
                        senha = txt
                    else:
                        QMessageBox.warning(self, "Juntar PDFs", f"“{os.path.basename(c)}”: {e}")
                        return
            lidos.append((bruto, senha))
        destino, _ = QFileDialog.getSaveFileName(self, "Salvar PDF juntado", self._caminho_livre(os.path.join(os.path.dirname(caminhos[0]), "juntado.pdf")), "PDF (*.pdf)")
        if not destino:
            return
        if not destino.lower().endswith(".pdf"):
            destino += ".pdf"

        def job(cb):
            dados = pdfops.juntar(lidos, cb)
            pdfops.escrever_atomico(destino, dados)
            return destino

        self.rodar(job, lambda p: self._oferecer_abrir(p, "PDFs juntados com sucesso."), "Juntando PDFs…", progresso=True)

    def _oferecer_abrir(self, caminho, msg):
        if QMessageBox.question(self, "Concluído", f"{msg}\n{caminho}\n\nDeseja abrir o arquivo agora?") == QMessageBox.StandardButton.Yes:
            self._abrir_caminho(caminho)

    def dividir(self):
        d = dialogs.DividirDialog(self, self.doc.num_paginas)
        if not d.exec():
            return
        modo, valor, pasta = d.valores()
        if not pasta:
            return
        base = self._nome_base()
        _snap, job0 = self.doc.preparar(lambda x: x)

        def job(cb):
            os.makedirs(pasta, exist_ok=True)
            partes = pdfops.dividir(job0(), modo, valor, cb)
            saidas = []
            for sufixo, dados in partes:
                caminho = self._caminho_livre(os.path.join(pasta, f"{base}_{sufixo}.pdf"))
                pdfops.escrever_atomico(caminho, dados)
                saidas.append(caminho)
            return saidas

        def pronto(saidas):
            QMessageBox.information(self, "Dividir PDF", f"{len(saidas)} arquivo(s) criado(s) em:\n{pasta}")

        self.rodar(job, pronto, "Dividindo o PDF…", progresso=True)

    def comprimir(self):
        antes = len(self.doc.dados)
        d = dialogs.ComprimirDialog(self, formatar_tamanho(antes))
        if not d.exec():
            return
        nivel = d.nivel()
        tinha_itens = bool(self.doc.itens)

        snap, job = self.doc.preparar(lambda x: pdfops.comprimir(x, nivel))

        def pronto(novos):
            depois = len(novos)
            if depois >= antes and not tinha_itens:
                QMessageBox.information(self, "Comprimir PDF", f"Este arquivo já está otimizado ({formatar_tamanho(antes)}). Nenhuma redução adicional foi possível neste nível.")
                return
            self.doc.confirmar(snap, novos)
            red = 100.0 * (1 - depois / antes) if antes else 0
            QMessageBox.information(self, "Comprimir PDF", f"Tamanho antes: {formatar_tamanho(antes)}\nTamanho depois: {formatar_tamanho(depois)}\nRedução: {red:.0f}%\n\nSalve o documento para gravar o resultado.")

        self.rodar(job, pronto, "Comprimindo…")

    def proteger(self):
        d = dialogs.ProtegerDialog(self)
        if not d.exec():
            return
        vals = d.valores()
        self._gravar_copia(lambda x: pdfops.proteger(x, **vals), "Salvar cópia protegida", f"{self._nome_base()}_protegido.pdf")

    def remover_senha(self):
        if not self.doc.senha:
            QMessageBox.information(self, "Remover senha", "Este documento foi aberto sem senha. Ao salvar, o arquivo ficará sem senha.")
            return
        if QMessageBox.question(self, "Remover senha", "Ao salvar, o arquivo deixará de pedir senha. Continuar?") == QMessageBox.StandardButton.Yes:
            self.doc.registrar()
            self.doc.senha = ""
            self.statusBar().showMessage("A senha será removida ao salvar.", 6000)

    # ------------------------------------------------------------------
    # Marca d'água, numeração, formulários
    # ------------------------------------------------------------------
    def marca_dagua(self):
        d = dialogs.MarcaDaguaDialog(self)
        if not d.exec():
            return
        v = d.valores()
        try:
            paginas = pdfops.parse_paginas(v["paginas"], self.doc.num_paginas)
            img = None
            if v["tipo"] == "imagem":
                with open(v["arquivo"], "rb") as f:
                    img = f.read()
        except (ValueError, OSError) as e:
            self._erro(e)
            return
        if v["tipo"] == "texto":
            fn = lambda x: overlay.marca_dagua_texto(x, v["texto"], paginas, v["tamanho"], v["opacidade"], v["angulo"], v["cor"])  # noqa: E731
        else:
            fn = lambda x: overlay.marca_dagua_imagem(x, img, paginas, 0.6, v["opacidade"])  # noqa: E731
        self._operacao(fn, "Aplicando marca d’água…")

    def numerar(self):
        d = dialogs.NumeracaoDialog(self)
        if not d.exec():
            return
        v = d.valores()
        try:
            paginas = pdfops.parse_paginas(v["paginas"], self.doc.num_paginas)
        except ValueError as e:
            self._erro(e)
            return
        self._operacao(lambda x: overlay.numerar_paginas(x, v["formato"], v["posicao"], v["inicio"], paginas, v["tamanho"]), "Numerando páginas…")

    def preencher_formulario(self):
        try:
            campos = pdfops.listar_campos(self.doc.dados)
        except Exception as e:  # noqa: BLE001
            self._erro(e)
            return
        if not campos:
            QMessageBox.information(self, "Formulário", "Este PDF não possui campos de formulário (AcroForm).")
            return
        d = dialogs.FormularioDialog(self, campos)
        if not d.exec():
            return
        valores, achatar = d.valores()

        def fn(x):
            r = pdfops.preencher_campos(x, valores)
            return pdfops.achatar_formulario(r) if achatar else r

        self._operacao(fn, "Preenchendo formulário…")

    def achatar_formulario(self):
        if not pdfops.listar_campos(self.doc.dados):
            QMessageBox.information(self, "Formulário", "Este PDF não possui campos de formulário.")
            return
        self._operacao(pdfops.achatar_formulario, "Achatando formulário…")

    # ------------------------------------------------------------------
    # Conversões
    # ------------------------------------------------------------------
    def imagens_para_pdf(self):
        d = dialogs.ListaArquivosDialog(self, "Imagens para PDF", "Imagens (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)", "Criar PDF…",
                                        checkbox="Ajustar cada imagem a uma página A4")
        if not d.exec():
            return
        caminhos, a4 = d.caminhos(), d.marcado()
        if not caminhos:
            QMessageBox.information(self, "Imagens para PDF", "Adicione ao menos uma imagem.")
            return
        destino, _ = QFileDialog.getSaveFileName(self, "Salvar PDF", self._caminho_livre(os.path.join(os.path.dirname(caminhos[0]), "imagens.pdf")), "PDF (*.pdf)")
        if not destino:
            return
        if not destino.lower().endswith(".pdf"):
            destino += ".pdf"

        def job(cb):
            pdfops.escrever_atomico(destino, imagens.imagens_para_pdf(caminhos, a4, cb))
            return destino

        self.rodar(job, lambda p: self._oferecer_abrir(p, "PDF criado a partir das imagens."), "Criando PDF…", progresso=True)

    def pdf_para_imagens(self):
        d = dialogs.PdfParaImagensDialog(self, self.doc.num_paginas)
        if not d.exec():
            return
        dpi, fmt, paginas_txt, pasta = d.valores()
        try:
            paginas = pdfops.parse_paginas(paginas_txt, self.doc.num_paginas) if paginas_txt.strip() else None
        except ValueError as e:
            self._erro(e)
            return
        base = self._nome_base()
        _snap, job0 = self.doc.preparar(lambda x: x)

        def job(cb):
            return imagens.pdf_para_imagens(job0(), pasta, base, dpi, fmt, paginas, cb)

        def pronto(arqs):
            QMessageBox.information(self, "Converter", f"{len(arqs)} imagem(ns) salva(s) em:\n{pasta}")

        self.rodar(job, pronto, "Convertendo páginas em imagens…", progresso=True)

    # ------------------------------------------------------------------
    def sobre(self):
        QMessageBox.about(self, "Sobre o Editor de PDF",
                          f"<b>Editor de PDF {__version__}</b><br>Funciona 100% offline: nenhum arquivo é enviado à internet e não há telemetria.<br><br>"
                          "Feito com Python, PySide6 (LGPL), pypdfium2, pikepdf, pypdf e reportlab.<br>"
                          "Veja o arquivo THIRD_PARTY_LICENSES.txt para as licenças.")


def QThreadPool_global():
    from PySide6.QtCore import QThreadPool
    return QThreadPool.globalInstance()
