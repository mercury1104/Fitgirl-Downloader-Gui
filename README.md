# FitGirl Easy Downloader GUI

Descarga juegos de **fitgirl-repacks.site** alojados en **fuckingfast.co** con múltiples descargas en paralelo.

---

## 🚀 Usar el .exe (recomendado)

1. Descargá `FitGirl-Downloader-GUI.exe`
2. Abrí el programa
3. Pegá la URL de un juego de FitGirl (ej: `https://fitgirl-repacks.site/...`)
4. Click **"Extraer enlaces"**
5. Click **"Iniciar descarga"**

No necesita instalar nada. Solo Windows 10/11 64-bit.

---

## 🐍 Usar desde Python

```bash
pip install -r requirements.txt
python gui.py
```

---

## 📦 Generar .exe propio

```bash
pip install pyinstaller
pyinstaller --onefile --name "FitGirl-Downloader-GUI" --add-data "web;web" gui.py
```

El .exe queda en `dist/FitGirl-Downloader-GUI.exe`.

---

## ⚠️ Disclaimer

Herramienta educativa. No nos responsabilizamos del mal uso que se le pueda dar.

---

## 👥 Créditos

- **[Aecito](https://github.com/Aecito)** — Adaptación HTMX, GUI web, debug
- **[JoyNath1337](https://github.com/JoyNath1337)** — Proyecto original FitGirl-Easy-Downloader
