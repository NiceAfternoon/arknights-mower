set -e
python_lib=$(python -c 'import sysconfig; print(sysconfig.get_path("platlib"))')
shopt -s nullglob nocaseglob
cp -a /usr/lib/python3/dist-packages/{gi,cairo,pygobject-*,pycairo-*} "$python_lib/"
xvfb-run -a python -c 'from importlib.metadata import version; print(version("PyGObject")); import cairo, gi; gi.require_foreign("cairo"); import webview.platforms.gtk'

