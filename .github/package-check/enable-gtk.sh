set -e
python_lib=$(python -c 'import sysconfig; print(sysconfig.get_path("platlib"))')
cp -a /usr/lib/python3/dist-packages/{gi,cairo} "$python_lib/"
xvfb-run -a python -c 'import cairo, gi; gi.require_foreign("cairo"); import webview.platforms.gtk'

