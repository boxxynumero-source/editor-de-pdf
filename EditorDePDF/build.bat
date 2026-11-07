@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================
echo  Gerando EditorDePDF.exe  (pode levar alguns minutos)
echo ============================================

where py >nul 2>nul
if errorlevel 1 (
  echo.
  echo [ERRO] Python nao encontrado. Instale o Python 3.11 ou 3.12 em https://www.python.org/downloads/
  echo        e MARQUE a opcao "Add python.exe to PATH" no instalador. Depois rode este arquivo de novo.
  echo        ^(Isto so e necessario na maquina que GERA o .exe. Quem apenas USA o .exe nao precisa de nada.^)
  pause
  exit /b 1
)

py -3 -m venv .venv || goto erro
call .venv\Scripts\activate.bat || goto erro
python -m pip install --upgrade pip || goto erro
pip install -r requirements.txt pyinstaller || goto erro

echo.
echo Rodando testes automaticos...
python -m unittest discover -s tests || goto erro

echo.
echo Compilando...
pyinstaller --noconfirm --clean --onefile --windowed --name EditorDePDF ^
  --collect-all pypdfium2 --collect-all pypdfium2_raw --collect-all pikepdf ^
  main.py || goto erro

echo.
echo Teste rapido do .exe (sem janela)...
set QT_QPA_PLATFORM=offscreen
dist\EditorDePDF.exe --autoteste
if errorlevel 1 (
  echo [AVISO] O autoteste do .exe falhou. Veja %TEMP%\EditorDePDF_autoteste.log
  type "%TEMP%\EditorDePDF_autoteste.log"
  pause
  exit /b 1
)
type "%TEMP%\EditorDePDF_autoteste.log"

echo.
echo ============================================
echo  PRONTO!  O programa esta em:  dist\EditorDePDF.exe
echo ============================================
pause
exit /b 0

:erro
echo.
echo [ERRO] Algo falhou. Role a tela para cima para ver a mensagem.
pause
exit /b 1
