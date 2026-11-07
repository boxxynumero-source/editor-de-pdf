"""Ponto de entrada da aplicação (e do autoteste usado na integração contínua)."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback


def _autoteste(app, JanelaPrincipal) -> int:
    """Roda a interface sem tela (QT_QPA_PLATFORM=offscreen): abre um PDF, renderiza,
    edita, salva e confere. Código de saída 0 = tudo certo."""
    import io

    import pikepdf
    from reportlab.pdfgen import canvas

    from ..core import pdfops
    from ..core.model import Item

    log_path = os.path.join(tempfile.gettempdir(), "EditorDePDF_autoteste.log")
    linhas = []

    def log(msg):
        linhas.append(msg)
        print(msg, flush=True)

    def esperar(cond, tempo=30.0, rotulo=""):
        fim = time.time() + tempo
        while time.time() < fim:
            app.processEvents()
            if cond():
                return True
            time.sleep(0.02)
        raise TimeoutError(f"tempo esgotado: {rotulo}")

    codigo = 0
    try:
        tmp = tempfile.mkdtemp()
        entrada, saida = os.path.join(tmp, "entrada.pdf"), os.path.join(tmp, "saida.pdf")
        c = canvas.Canvas(entrada)
        for i in range(3):
            c.drawString(100, 700, f"Pagina {i + 1}")
            c.showPage()
        c.save()

        j = JanelaPrincipal()
        j.show()
        j._abrir_sem_confirmar(entrada)
        esperar(lambda: j.doc is not None, rotulo="abrir")
        log("OK abrir documento")
        esperar(lambda: j.vista.pixmap_de(0) is not None, rotulo="renderizar página 1")
        log("OK renderização da página (pdfium)")
        esperar(lambda: j.miniaturas.count() == 3 and not j.miniaturas.item(2).icon().isNull(), rotulo="miniaturas")
        log("OK miniaturas")
        j.doc.adicionar_item(Item("text", 0, x=50, y=50, text="Teste ação", size=18))
        j.vista.definir_zoom(1.5)
        j.vista.ajustar_largura()
        j.vista.ir_para(2)
        app.processEvents()
        j._operacao(lambda d: pdfops.girar(d, [0], 90), "teste")
        esperar(lambda: not j._ocupado and j.doc.num_paginas == 3 and not j.doc.itens, rotulo="girar")
        j.doc.desfazer()
        j.doc.refazer()
        log("OK edição, girar, desfazer/refazer")
        j.doc.adicionar_item(Item("rect", 1, x=10, y=10, w=50, h=50, color="#ff0000", fill="#ff0000"))
        j._gravar(saida)
        esperar(lambda: not j._ocupado and not j.doc.sujo, rotulo="salvar")
        with pikepdf.open(io.BytesIO(pdfops.ler_arquivo(saida))) as p:
            assert len(p.pages) == 3
        log("OK salvar PDF válido")
        j.doc.sujo = False
        log("AUTOTESTE: SUCESSO")
    except Exception:  # noqa: BLE001
        codigo = 1
        log("AUTOTESTE: FALHA\n" + traceback.format_exc())
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(linhas))
    except OSError:
        pass
    return codigo


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    autoteste = "--autoteste" in argv
    if autoteste:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, QTranslator
    from PySide6.QtWidgets import QApplication

    app = QApplication(argv)
    app.setApplicationName("EditorDePDF")
    app.setOrganizationName("EditorDePDF")
    app.setApplicationDisplayName("Editor de PDF")
    QLocale.setDefault(QLocale("pt_BR"))
    tr = QTranslator()
    if tr.load("qtbase_pt_BR", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(tr)

    from .mainwindow import JanelaPrincipal
    from .tasks import aplicar_tema, iniciar_log

    iniciar_log()
    escuro = QSettings("EditorDePDF", "EditorDePDF").value("escuro", False, type=bool)
    aplicar_tema(app, escuro)

    if autoteste:
        code = _autoteste(app, JanelaPrincipal)
        sys.stdout.flush()
        os._exit(code)

    arquivo = next((a for a in argv[1:] if not a.startswith("--") and a.lower().endswith(".pdf") and os.path.isfile(a)), None)
    janela = JanelaPrincipal(arquivo)
    janela.show()
    sys.exit(app.exec())
