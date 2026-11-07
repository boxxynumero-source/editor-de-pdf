"""Testa a lógica de desfazer/refazer/salvar do documento.
Usa o PySide6 real se instalado; senão, um stub mínimo de QObject/Signal."""
import io
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import PySide6.QtCore  # noqa: F401
except ImportError:  # ambiente sem Qt (apenas para testar a lógica)
    class _Sinal:
        def __init__(self):
            self._s = []

        def connect(self, f):
            self._s.append(f)

        def disconnect(self, f=None):
            self._s.remove(f)

        def emit(self, *a):
            for f in list(self._s):
                f(*a)

    class Signal:
        def __init__(self, *t):
            pass

        def __set_name__(self, o, n):
            self.n = "_sig_" + n

        def __get__(self, obj, typ=None):
            if obj is None:
                return self
            return obj.__dict__.setdefault(self.n, _Sinal())

    class QObject:
        def __init__(self, *a, **k):
            pass

    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.QObject, qtcore.Signal = QObject, Signal
    pkg = types.ModuleType("PySide6")
    pkg.QtCore = qtcore
    sys.modules.update({"PySide6": pkg, "PySide6.QtCore": qtcore})

import pikepdf  # noqa: E402

from editor_pdf.core import pdfops  # noqa: E402
from editor_pdf.core.model import Item  # noqa: E402
from editor_pdf.ui.document import Documento  # noqa: E402
from tests.test_core import gerar_pdf, textos  # noqa: E402


class TestDocumento(unittest.TestCase):
    def test_itens_desfazer_refazer(self):
        d = Documento(gerar_pdf(2))
        self.assertFalse(d.sujo)
        it = Item("text", 0, x=10, y=10, text="olá")
        d.adicionar_item(it)
        self.assertTrue(d.sujo and d.pode_desfazer())
        self.assertEqual(len(d.itens), 1)
        d.desfazer()
        self.assertEqual(len(d.itens), 0)
        self.assertTrue(d.pode_refazer())
        d.refazer()
        self.assertEqual(len(d.itens), 1)

    def test_operacao_estrutural_consolida_e_desfaz(self):
        d = Documento(gerar_pdf(3))
        avisos = []
        d.estrutura_mudou.connect(lambda: avisos.append(1))
        d.adicionar_item(Item("text", 0, x=50, y=50, text="CARIMBO"))
        snap, job = d.preparar(lambda x: pdfops.excluir(x, [2]))
        novos = job()
        d.confirmar(snap, novos)
        self.assertEqual(d.num_paginas, 2)
        self.assertEqual(d.itens, [])
        self.assertIn("CARIMBO", textos(d.dados)[0])  # item foi "assado" no PDF
        d.desfazer()
        self.assertEqual(d.num_paginas, 3)
        self.assertEqual(len(d.itens), 1)  # item de volta, editável
        self.assertNotIn("CARIMBO", textos(d.dados)[0])
        d.refazer()
        self.assertEqual(d.num_paginas, 2)
        self.assertGreaterEqual(len(avisos), 3)

    def test_salvar_com_itens_e_senha_original(self):
        d = Documento(gerar_pdf(1), senha="s3nh4")
        d.adicionar_item(Item("text", 0, x=50, y=50, text="Visivel"))
        out = d.preparar_salvar()()
        with self.assertRaises(pdfops.SenhaNecessaria):
            pdfops.abrir(out)
        livre = pdfops.normalizar(out, "s3nh4")
        self.assertIn("Visivel", textos(livre)[0])
        d.senha = ""  # "remover senha"
        out2 = d.preparar_salvar()()
        pdfops.abrir(out2).close()

    def test_desfazer_limitado(self):
        d = Documento(gerar_pdf(1))
        for i in range(60):
            d.adicionar_item(Item("text", 0, text=str(i)))
        n = 0
        while d.pode_desfazer():
            d.desfazer()
            n += 1
        self.assertEqual(n, 40)


if __name__ == "__main__":
    unittest.main()
