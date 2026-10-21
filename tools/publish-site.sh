#!/bin/sh
# Publish Kilobyte's website on GitHub Pages (https://jgm240.github.io/kilobyte/):
# the pages in site/, the "Try it" virtual PC from out/web-vm (made by
# tools/make-web-vm.sh), next to the APT repository in apt/ (kept as it is;
# tools/publish-apt-repo.sh makes it).
#
# The gh-pages branch is only ever made by these scripts: it is published as
# one fresh commit each time, so the virtual PC's hundreds of MB do not pile
# up in its history. Everything on it comes from this repository and out/.
set -e
cd "$(dirname "$0")/.."
W=out/gh-pages
REMOTE=$(git remote get-url origin)
[ -d "$W/.git" ] || git clone -q --branch gh-pages "$REMOTE" "$W"
git -C "$W" fetch -q origin gh-pages && git -C "$W" reset -q --hard origin/gh-pages

# The pages (site/; its "try" is only a link to out/web-vm for previewing),
# then the virtual PC: the emulator, and the disk once it is made.
rsync -a --exclude try --exclude .DS_Store site/ "$W/"
mkdir -p "$W/try"
[ -d out/web-vm/v86 ] && rsync -a --delete out/web-vm/v86/ "$W/try/v86/"
if [ -f out/web-vm/disk/manifest.json ]; then
    rsync -a --delete out/web-vm/disk/ "$W/try/disk/"
else
    echo "(no virtual PC disk in out/web-vm yet: the Try page says it is coming; tools/make-web-vm.sh makes it)"
fi
# The text version's Download page lists the newest release's files itself
# (text browsers cannot ask GitHub's API the way the graphical page does).
gh api repos/jgm240/kilobyte/releases/latest > out/latest-release.json 2>/dev/null &&
python3 - "$W/html/download.html" out/latest-release.json <<'PY' || echo "(the text Download page keeps its link to the release page)"
import html, json, re, sys
page, rel = sys.argv[1], json.load(open(sys.argv[2]))
kinds = [(r"-amd64\.iso$", "64-bit PC (ISO)"), (r"-amd64-usb\.img$", "64-bit PC (USB stick)"),
         (r"-i386\.iso$", "32-bit PC (ISO)"), (r"-i386-usb\.img$", "32-bit PC (USB stick)"),
         (r"-i386-cd\.iso$", "CD version, for PCs from the 1990s"),
         (r"-raspberrypi-arm64\.img\.xz$", "Raspberry Pi 3, 4, 400, 5, 500, Zero 2 W"),
         (r"-raspberrypi-armhf\.img\.xz$", "Raspberry Pi 2, 3 (32-bit)"),
         (r"-raspberrypi-armel\.img\.xz$", "Raspberry Pi 1, Zero, Zero W"),
         (r"^(kilobyteink|kinlobyte)-.*\.zip$", "KilobytEink, for jailbroken Kindles")]
items = []
for rx, what in kinds:
    for a in rel["assets"]:
        if re.search(rx, a["name"]):
            mb = a["size"] / 1e6
            size = "%.1f GB" % (mb / 1000) if mb >= 1000 else "%d MB" % mb
            items.append('<li><a href="%s">%s</a>: %s, %s</li>' % (html.escape(a["browser_download_url"]),
                         html.escape(a["name"]), html.escape(what), size))
block = ("<p>%s:</p>\n<ul>\n%s\n</ul>\n<p>Each file has a .sha256 checksum next to it on "
         '<a href="%s">the release page</a>, with the list of source packages of each image.</p>'
         % (html.escape(rel.get("name") or rel["tag_name"]), "\n".join(items), html.escape(rel["html_url"])))
s = open(page).read()
s = re.sub(r"<!--DOWNLOADS-->.*<!--/DOWNLOADS-->", lambda m: "<!--DOWNLOADS-->\n" + block + "\n<!--/DOWNLOADS-->", s, flags=re.S)
open(page, "w").write(s)
print("text Download page: %d files of %s" % (len(items), rel["tag_name"]))
PY
: > "$W/.nojekyll"

# One commit with everything, replacing the branch.
git -C "$W" checkout -q --orphan site-new
git -C "$W" add -A
git -C "$W" commit -q -m "Kilobyte website ($(git rev-parse --short HEAD))"
git -C "$W" branch -q -D gh-pages
git -C "$W" branch -q -m gh-pages
git -C "$W" push -q --force origin gh-pages
du -sh "$W" --exclude=.git 2>/dev/null || du -sh "$W"
echo "Published: https://jgm240.github.io/kilobyte/"
