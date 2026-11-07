"""Estado do documento aberto: bytes do PDF + itens pendentes + desfazer/refazer."""
from __future__ import annotations

import copy

from PySide6.QtCore import QObject, Signal

from ..core import overlay, pdfops
from ..core.model import Item

LIMITE_DESFAZER = 40


class Documento(QObject):
    estrutura_mudou = Signal()  # os bytes (páginas) mudaram
    itens_mudaram = Signal()    # só as camadas pendentes mudaram
    estado_mudou = Signal()     # desfazer/refazer/sujo/título

    def __init__(self, dados: bytes, caminho: str | None = None, senha: str = ""):
        super().__init__()
        self.dados = dados
        self.caminho = caminho
        self.senha = senha
        self.itens: list[Item] = []
        self.versao = 0
        self.sujo = False
        self._undo: list = []
        self._redo: list = []
        self.num_paginas = pdfops.num_paginas(dados)

    # -- snapshots ---------------------------------------------------------
    def _snapshot(self):
        return (self.dados, copy.deepcopy(self.itens), self.senha)

    def _restaurar(self, snap):
        dados, itens, senha = snap
        mudou = dados is not self.dados
        self.dados, self.itens, self.senha = dados, itens, senha
        if mudou:
            self.versao += 1
            self.num_paginas = pdfops.num_paginas(dados)
            self.estrutura_mudou.emit()
        self.itens_mudaram.emit()

    def registrar(self):
        """Chamar ANTES de alterar (guarda o estado atual para desfazer)."""
        self._undo.append(self._snapshot())
        del self._undo[:-LIMITE_DESFAZER]
        self._redo.clear()
        self.sujo = True
        self.estado_mudou.emit()

    def pode_desfazer(self):
        return bool(self._undo)

    def pode_refazer(self):
        return bool(self._redo)

    def desfazer(self):
        if not self._undo:
            return
        self._redo.append(self._snapshot())
        self._restaurar(self._undo.pop())
        self.sujo = True
        self.estado_mudou.emit()

    def refazer(self):
        if not self._redo:
            return
        self._undo.append(self._snapshot())
        self._restaurar(self._redo.pop())
        self.sujo = True
        self.estado_mudou.emit()

    # -- itens -------------------------------------------------------------
    def adicionar_item(self, it: Item):
        self.registrar()
        self.itens.append(it)
        self.itens_mudaram.emit()

    def adicionar_itens(self, itens):
        self.registrar()
        self.itens.extend(itens)
        self.itens_mudaram.emit()

    def remover_item(self, it: Item):
        if it in self.itens:
            self.registrar()
            self.itens.remove(it)
            self.itens_mudaram.emit()

    # -- operações que alteram o PDF (consolidam os itens antes) ------------
    def preparar(self, funcao):
        """Devolve (snapshot, job). `job()` pode rodar em segundo plano: aplica
        os itens pendentes e depois `funcao(bytes)`. Depois chame `confirmar`."""
        dados = self.dados
        itens = copy.deepcopy(self.itens)
        snap = self._snapshot()

        def job():
            d = overlay.aplicar_itens(dados, itens) if itens else dados
            return funcao(d)

        return snap, job

    def confirmar(self, snap, novos: bytes):
        self._undo.append(snap)
        del self._undo[:-LIMITE_DESFAZER]
        self._redo.clear()
        self.dados = novos
        self.itens = []
        self.versao += 1
        self.num_paginas = pdfops.num_paginas(novos)
        self.sujo = True
        self.estrutura_mudou.emit()
        self.itens_mudaram.emit()
        self.estado_mudou.emit()

    # -- salvar ------------------------------------------------------------
    def preparar_salvar(self):
        """job() -> bytes finais (com itens aplicados e senha original, se havia)."""
        dados = self.dados
        itens = copy.deepcopy(self.itens)
        senha = self.senha

        def job():
            d = overlay.aplicar_itens(dados, itens) if itens else dados
            d = pdfops.normalizar(d)  # garante um PDF íntegro e normalizado
            if senha:
                d = pdfops.proteger(d, senha_abrir=senha)
            return d

        return job

    def marcar_salvo(self, caminho: str):
        self.caminho = caminho
        self.sujo = False
        self.estado_mudou.emit()
