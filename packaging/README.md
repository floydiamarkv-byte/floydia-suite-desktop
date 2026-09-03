# 📦 Empaquetado de FloydIA Suite 2.0

Estrategia de distribución multi-target. **Requisito previo (importante)**: la suite
detecta su workspace subiendo desde `__file__` buscando markers (`.env`, `requirements.txt`).
En instalaciones empaquetadas el árbol vive bajo `/usr/share/floydia-suite` (PKGBUILD) o en
el AppDir `/usr/src/floydia-suite`; los módulos ya resuelven el fallback portable a la raíz
del repo, así que estos paquetes funcionan sin rutas personales hardcodeadas. Para datos de
usuario se usan rutas XDG (`~/.config/floydia-suite/`, `~/.cache/`, `FLOYDIA_WORKSPACE`),
con `~/.config/floydia-suite/secrets.env` (0600) como candidato de secretos.

## 🟦 AUR / Arch Linux — `PKGBUILD`

```bash
makepkg -si          # construye e instala floydia-suite
floydia-suite        # lanza la suite
```

Instala el árbol en `/usr/share/floydia-suite`, launcher en `/usr/bin`,
`.desktop` en `/usr/share/applications` e icono en pixmaps.

> **GIT build**: para un paquete que siga `main` (recomendado mientras la versión
> acelera), usa este PKGBUILD sustituyendo `source` por:
> `git+https://github.com/floydiamarkv-byte/floydia-suite-desktop` y `pkgver()`
> con `git describe`.

## 🟩 AppImage — `make_appimage.sh`

```bash
./packaging/make_appimage.sh
# → build/dist/FloydIA-Suite-x86_64.AppImage
```

El script empaqueta un AppDir portable con el launcher y (si hay
`python-appimage`) genera el AppImage con runtime Python 3.10 y PyQt6.
Sin `python-appimage`, deja el AppDir listo para `linuxdeploy`.

## 🟨 Flatpak (roadmap)

Flatpak requiere sandbox; la suite necesita acceso a los configs de agentes
(`~/.config/opencode`, `~/.hermes`, `~/.qoder`, `~/.dsh`, `~/.gemini`). Un
manifest válido debe otorgar `--filesystem=home` (o por portal) a esas rutas.
Ver `docs/` para el diseño cuando se implemente.

## 🔑 Jerarquía de datos (XDG)

| Dato | Ruta |
|---|---|
| Config / secretos | `~/.config/floydia-suite/` (`.env`, `secrets.env` 0600) |
| Registro de ownership MCP | `~/.config/floydia-suite/managed-resources.json` |
| Caché / estado sesión | `~/.cache/floydia-suite/` o `cache/` del repo |
| Override de workspace | `FLOYDIA_WORKSPACE` (variable de entorno) |