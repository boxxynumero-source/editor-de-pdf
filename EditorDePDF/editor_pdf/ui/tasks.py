"""Execução em segundo plano (QThreadPool) e tema claro/escuro."""
from __future__ import annotations

import logging
import os
import traceback

from PySide6.QtCore import QObject, QRunnable, QStandardPaths, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def pasta_dados() -> str:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation) or os.path.expanduser("~/.editor_de_pdf")
    os.makedirs(base, exist_ok=True)
    return base


def iniciar_log():
    try:
        logging.basicConfig(filename=os.path.join(pasta_dados(), "erros.log"), level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s")
    except OSError:
        pass


class Sinais(QObject):
    concluido = Signal(object)
    erro = Signal(object)
    progresso = Signal(int, int)


class Tarefa(QRunnable):
    def __init__(self, fn, com_progresso=False):
        super().__init__()
        self.fn = fn
        self.com_progresso = com_progresso
        self.sinais = Sinais()
        self.setAutoDelete(False)

    def run(self):
        try:
            if self.com_progresso:
                r = self.fn(lambda i, n: self.sinais.progresso.emit(int(i), int(n)))
            else:
                r = self.fn()
        except Exception as e:  # noqa: BLE001
            logging.error("Falha em tarefa: %s", traceback.format_exc())
            self.sinais.erro.emit(e)
        else:
            self.sinais.concluido.emit(r)


def aplicar_tema(app: QApplication, escuro: bool):
    app.setStyle("Fusion")
    p = QPalette()
    if escuro:
        fundo, base, texto, dest = QColor(45, 45, 48), QColor(30, 30, 32), QColor(230, 230, 230), QColor(0, 120, 215)
        p.setColor(QPalette.ColorRole.Window, fundo)
        p.setColor(QPalette.ColorRole.WindowText, texto)
        p.setColor(QPalette.ColorRole.Base, base)
        p.setColor(QPalette.ColorRole.AlternateBase, fundo)
        p.setColor(QPalette.ColorRole.Text, texto)
        p.setColor(QPalette.ColorRole.Button, fundo)
        p.setColor(QPalette.ColorRole.ButtonText, texto)
        p.setColor(QPalette.ColorRole.ToolTipBase, base)
        p.setColor(QPalette.ColorRole.ToolTipText, texto)
        p.setColor(QPalette.ColorRole.Highlight, dest)
        p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(120, 120, 120))
        p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(120, 120, 120))
    else:
        p = app.style().standardPalette()
    app.setPalette(p)
    app.setStyleSheet("QToolBar{spacing:3px;padding:3px;} QToolButton{padding:3px 6px;border-radius:4px;}"
                      "QToolButton:checked{background:%s;color:white;}" % ("#0b6fc2" if escuro else "#2b7fd4"))
