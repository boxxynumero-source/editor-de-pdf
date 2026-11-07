"""Testes do motor de PDF (sem interface gráfica).
Executar:  python -m unittest discover -s tests -v
"""
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pikepdf
import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from editor_pdf.core import imagens, overlay, pdfops
from editor_pdf.core.model import Item

SEGREDO = "CPF 123.456.789-00"


def gerar_pdf(n=3, segredo_na=1, rotacoes=None):
    b = io.BytesIO()
    c = canvas.Canvas(b, pagesize=A4)
    for i in range(n):
        c.setFont("Helvetica", 24)
        c.drawString(72, 750, f"Pagina {i + 1}")
        c.setFont("Helvetica", 14)
        c.drawString(72, 700, f"Conteudo da pagina {i + 1}: ação, coração")
        if i == segredo_na:
            c.drawString(72, 650, SEGREDO)
        c.showPage()
    c.save()
    dados = b.getvalue()
    if rotacoes:
        with pikepdf.open(io.BytesIO(dados)) as pdf:
            for i, r in rotacoes.items():
                pdf.pages[i].Rotate = r
            o = io.BytesIO()
            pdf.save(o)
            dados = o.getvalue()
    return dados


def textos(dados):
    r = PdfReader(io.BytesIO(dados))
    return [(p.extract_text() or "") for p in r.pages]


def pixel(dados, pagina, x_pt, y_pt, escala=1.0):
    d = pdfium.PdfDocument(dados)
    try:
        pg = d[pagina]
        im = pg.render(scale=escala).to_pil().convert("RGB")
        pg.close()
        return im.getpixel((int(x_pt * escala), int(y_pt * escala)))
    finally:
        d.close()


def tudo_no_arquivo(dados, trecho: str) -> bool:
    """Procura o trecho no arquivo bruto e em todos os streams decodificados."""
    if trecho.encode() in dados:
        return True
    with pikepdf.open(io.BytesIO(dados)) as pdf:
        for obj in pdf.objects:
            if isinstance(obj, pikepdf.Stream):
                try:
                    if trecho.encode("latin-1") in obj.read_bytes():
                        return True
                except Exception:
                    pass
    return False


class TestOrganizar(unittest.TestCase):
    def test_juntar(self):
        a, b = gerar_pdf(2), gerar_pdf(3)
        r = pdfops.juntar([(a, ""), (b, "")])
        self.assertEqual(pdfops.num_paginas(r), 5)
        self.assertIn("Pagina 1", textos(r)[2])

    def test_dividir_modos(self):
        d = gerar_pdf(5)
        partes = pdfops.dividir(d, "intervalos", "1-2, 4")
        self.assertEqual([pdfops.num_paginas(p) for _, p in partes], [2, 1])
        partes = pdfops.dividir(d, "cada_n", 2)
        self.assertEqual([pdfops.num_paginas(p) for _, p in partes], [2, 2, 1])
        partes = pdfops.dividir(d, "uma_por_pagina")
        self.assertEqual(len(partes), 5)
        self.assertIn("Pagina 3", textos(partes[2][1])[0])

    def test_intervalo_invalido(self):
        with self.assertRaises(ValueError):
            pdfops.parse_paginas("9-12", 5)
        with self.assertRaises(ValueError):
            pdfops.parse_paginas("abc", 5)
        self.assertEqual(pdfops.parse_paginas("2-", 4), [1, 2, 3])

    def test_girar(self):
        r = pdfops.girar(gerar_pdf(3), [1], 90)
        with pikepdf.open(io.BytesIO(r)) as p:
            self.assertEqual(int(p.pages[1].get("/Rotate", 0)), 90)
            self.assertEqual(int(p.pages[0].get("/Rotate", 0)), 0)
        r = pdfops.girar(r, [1], 90)
        with pikepdf.open(io.BytesIO(r)) as p:
            self.assertEqual(int(p.pages[1].get("/Rotate", 0)), 180)

    def test_excluir_duplicar_reordenar_extrair_branco(self):
        d = gerar_pdf(3)
        r = pdfops.excluir(d, [0])
        self.assertEqual(pdfops.num_paginas(r), 2)
        self.assertIn("Pagina 2", textos(r)[0])
        with self.assertRaises(pdfops.PdfError):
            pdfops.excluir(d, [0, 1, 2])
        r = pdfops.duplicar(d, [0])
        self.assertEqual([("Pagina 1" in t) for t in textos(r)], [True, True, False, False])
        r = pdfops.reordenar(d, [2, 0, 1])
        self.assertEqual([t.split()[1] for t in textos(r)], ["3", "1", "2"])
        r = pdfops.extrair(d, [0, 2])
        self.assertEqual(pdfops.num_paginas(r), 2)
        self.assertIn("Pagina 3", textos(r)[1])
        r = pdfops.inserir_em_branco(d, 1)
        self.assertEqual(pdfops.num_paginas(r), 4)
        self.assertEqual(textos(r)[1].strip(), "")
        self.assertIn("Pagina 2", textos(r)[2])


class TestSenha(unittest.TestCase):
    def test_proteger_e_remover(self):
        d = gerar_pdf(2)
        p = pdfops.proteger(d, senha_abrir="abc123")
        with self.assertRaises(pdfops.SenhaNecessaria):
            pdfops.abrir(p)
        with self.assertRaises(pdfops.SenhaIncorreta):
            pdfops.abrir(p, "errada")
        livre = pdfops.normalizar(p, "abc123")
        self.assertEqual(pdfops.num_paginas(livre), 2)
        self.assertNotIn(b"/Encrypt", livre)

    def test_senha_de_edicao(self):
        p = pdfops.proteger(gerar_pdf(1), senha_editar="dono", permitir_editar=False, permitir_copiar=False)
        with pikepdf.open(io.BytesIO(p)) as pdf:  # abre sem senha (só permissões)
            self.assertTrue(pdf.is_encrypted)
            self.assertFalse(pdf.allow.modify_other)
            self.assertFalse(pdf.allow.extract)
        with self.assertRaises(ValueError):
            pdfops.proteger(gerar_pdf(1))


class TestRedacao(unittest.TestCase):
    def test_remove_de_verdade(self):
        d = gerar_pdf(3, segredo_na=1)
        self.assertTrue(tudo_no_arquivo(d, SEGREDO) or SEGREDO in textos(d)[1])
        self.assertIn(SEGREDO, textos(d)[1])
        # linha do segredo em y_pdf=650 -> y visível = 841.89-650 ≈ 192
        it = Item("tarja", 1, x=60, y=170, w=300, h=40, color="#000000")
        r = overlay.aplicar_itens(d, [it])
        self.assertEqual(pdfops.num_paginas(r), 3)
        self.assertNotIn("123.456", textos(r)[1])
        self.assertFalse(tudo_no_arquivo(r, "123.456"))
        self.assertFalse(tudo_no_arquivo(r, "CPF"))
        # a tarja está preta
        self.assertLess(sum(pixel(r, 1, 100, 190)), 60)
        # outras páginas continuam com texto
        self.assertIn("Pagina 1", textos(r)[0])
        self.assertIn("Pagina 3", textos(r)[2])

    def test_texto_na_area(self):
        d = gerar_pdf(3, segredo_na=1)
        t = pdfops.texto_na_area(d, 1, 60, 170, 300, 40)
        self.assertIn("123.456", t)


class TestOverlay(unittest.TestCase):
    def test_texto_aparece(self):
        d = gerar_pdf(2)
        it = Item("text", 0, x=100, y=300, text="Olá, João! Ação", size=18)
        r = overlay.aplicar_itens(d, [it])
        self.assertIn("João", textos(r)[0])

    def test_posicao_em_todas_as_rotacoes(self):
        for rot in (0, 90, 180, 270):
            d = gerar_pdf(1, rotacoes={0: rot} if rot else None)
            # retângulo vermelho em (50,50) tamanho 40x40 no quadro visível
            it = Item("rect", 0, x=50, y=50, w=40, h=40, color="#FF0000", fill="#FF0000")
            r = overlay.aplicar_itens(d, [it])
            r_, g, b = pixel(r, 0, 70, 70)
            self.assertGreater(r_, 200, f"rotação {rot}")
            self.assertLess(g, 60, f"rotação {rot}")
            # fora do retângulo continua branco
            self.assertGreater(sum(pixel(r, 0, 120, 120)), 700, f"rotação {rot}")

    def test_todas_as_anotacoes(self):
        d = gerar_pdf(1)
        itens = [
            Item("highlight", 0, x=60, y=100, w=100, h=14, color="#FFEB3B"),
            Item("underline", 0, x=60, y=130, w=100, h=14, color="#FF0000"),
            Item("strike", 0, x=60, y=160, w=100, h=14, color="#0000FF"),
            Item("pen", 0, points=[(200, 200), (220, 230), (260, 210)], color="#00AA00", width=3),
            Item("ellipse", 0, x=300, y=300, w=60, h=40, color="#000000", width=2),
            Item("arrow", 0, points=[(300, 400), (400, 450)], color="#AA00AA", width=2),
            Item("note", 0, x=300, y=500, text="Nota\nem duas linhas", fill="#FFF59D", size=11),
        ]
        r = overlay.aplicar_itens(d, itens)
        self.assertEqual(pdfops.num_paginas(r), 1)
        self.assertIn("duas linhas", textos(r)[0])
        pdfops.abrir(r).close()

    def test_imagem_e_assinatura(self):
        im = Image.new("RGBA", (50, 30), (0, 0, 255, 255))
        b = io.BytesIO()
        im.save(b, "PNG")
        it = Item("image", 0, x=100, y=100, w=100, h=60, image=b.getvalue())
        r = overlay.aplicar_itens(gerar_pdf(1), [it])
        pr, pg, pb = pixel(r, 0, 150, 130)
        self.assertGreater(pb, 200)
        self.assertLess(pr, 60)

    def test_marca_dagua_e_numeracao(self):
        d = gerar_pdf(3)
        r = overlay.marca_dagua_texto(d, "CONFIDENCIAL", [0, 2])
        self.assertIn("CONFIDENCIAL", textos(r)[0])
        self.assertNotIn("CONFIDENCIAL", textos(r)[1])
        r = overlay.numerar_paginas(d, "Página {n} de {total}", posicao=1, paginas=[0, 1, 2])
        self.assertIn("Página 3 de 3", textos(r)[2])
        r = overlay.numerar_paginas(d, "{n}", posicao=3, inicio=10, paginas=[1])
        self.assertIn("10", textos(r)[1])

    def test_marca_dagua_imagem(self):
        im = Image.new("RGB", (40, 40), (255, 0, 0))
        b = io.BytesIO()
        im.save(b, "PNG")
        r = overlay.marca_dagua_imagem(gerar_pdf(1), b.getvalue(), [0], escala=0.5, opacidade=1.0)
        self.assertGreater(pixel(r, 0, 297, 421)[0], 200)

    def test_resultado_abre_no_pdfium_e_pikepdf(self):
        d = gerar_pdf(2)
        r = overlay.aplicar_itens(d, [Item("text", 1, x=10, y=10, text="x")])
        with pikepdf.open(io.BytesIO(r)) as p:
            self.assertEqual(len(p.pages), 2)
            self.assertEqual(p.check_pdf_syntax(), [])


class TestCompressao(unittest.TestCase):
    def test_comprime_imagem_grande(self):
        import random

        random.seed(1)
        im = Image.effect_noise((1600, 1600), 40).convert("RGB")
        arq = io.BytesIO()
        im.save(arq, "PNG")
        arq.seek(0)
        b = io.BytesIO()
        c = canvas.Canvas(b, pagesize=A4)
        from reportlab.lib.utils import ImageReader

        c.drawImage(ImageReader(arq), 20, 100, 500, 500)
        c.showPage()
        c.save()
        d = b.getvalue()
        leve = pdfops.comprimir(d, "leve")
        medio = pdfops.comprimir(d, "medio")
        forte = pdfops.comprimir(d, "forte")
        self.assertLessEqual(len(leve), len(d))
        self.assertLess(len(medio), len(d) * 0.6)
        self.assertLessEqual(len(forte), len(medio))
        self.assertEqual(pdfops.num_paginas(forte), 1)


class TestFormulario(unittest.TestCase):
    def _form(self):
        b = io.BytesIO()
        c = canvas.Canvas(b, pagesize=A4)
        c.drawString(72, 780, "Formulario")
        c.acroForm.textfield(name="nome", x=72, y=700, width=200, height=22, value="", borderStyle="solid")
        c.acroForm.checkbox(name="aceito", x=72, y=650, size=16, checked=False)
        c.showPage()
        c.save()
        return b.getvalue()

    def test_listar_preencher_achatar(self):
        d = self._form()
        campos = {c["nome"]: c for c in pdfops.listar_campos(d)}
        self.assertEqual(campos["nome"]["tipo"], "texto")
        self.assertEqual(campos["aceito"]["tipo"], "caixa")
        r = pdfops.preencher_campos(d, {"nome": "Maria da Conceição"})
        self.assertEqual({c["nome"]: c for c in pdfops.listar_campos(r)}["nome"]["valor"], "Maria da Conceição")
        flat = pdfops.achatar_formulario(r)
        self.assertEqual(pdfops.listar_campos(flat), [])
        self.assertIn("Maria", textos(flat)[0])


class TestImagens(unittest.TestCase):
    def test_ida_e_volta(self):
        with tempfile.TemporaryDirectory() as t:
            caminhos = []
            for i, cor in enumerate([(255, 0, 0), (0, 255, 0)]):
                p = os.path.join(t, f"i{i}.png")
                Image.new("RGB", (300, 200), cor).save(p)
                caminhos.append(p)
            pdf = imagens.imagens_para_pdf(caminhos)
            self.assertEqual(pdfops.num_paginas(pdf), 2)
            pdf2 = imagens.imagens_para_pdf(caminhos, ajustar_a4=False)
            self.assertEqual(pdfops.num_paginas(pdf2), 2)
            saidas = imagens.pdf_para_imagens(pdf, os.path.join(t, "out"), "pg", dpi=72, formato="png")
            self.assertEqual(len(saidas), 2)
            im = Image.open(saidas[0])
            self.assertEqual(im.size, (842, 596))  # imagem paisagem -> A4 deitado
            im.close()
            saidas = imagens.pdf_para_imagens(pdf, os.path.join(t, "out"), "pg", dpi=96, formato="jpg", paginas=[1])
            self.assertTrue(saidas[0].endswith(".jpg"))

    def test_assinatura(self):
        im = Image.new("RGBA", (100, 60), (255, 255, 255, 255))
        for x in range(30, 60):
            im.putpixel((x, 30), (0, 0, 0, 255))
        b = io.BytesIO()
        im.save(b, "PNG")
        r = Image.open(io.BytesIO(imagens.remover_fundo_branco(b.getvalue())))
        self.assertEqual(r.size, (30, 1))


class TestArquivo(unittest.TestCase):
    def test_corrompido_e_gravacao(self):
        with self.assertRaises(pdfops.PdfError):
            pdfops.abrir(b"isto nao e um pdf")
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "a.pdf")
            pdfops.escrever_atomico(p, gerar_pdf(1))
            self.assertEqual(pdfops.num_paginas(pdfops.ler_arquivo(p)), 1)
            self.assertEqual(os.listdir(t), ["a.pdf"])
        with self.assertRaises(pdfops.PdfError):
            pdfops.ler_arquivo("/nao/existe.pdf")


if __name__ == "__main__":
    unittest.main(verbosity=2)
