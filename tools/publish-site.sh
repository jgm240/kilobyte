#!/bin/sh
# Publish Kilobyte's website on GitHub Pages (https://jgm240.github.io/kilobyte/):
# the pages in site/, the "Try it" virtual PC from out/web-vm (made by
# tools/make-web-vm.sh), next to the APT repository in apt/ (kept as it is;
# tools/publish-apt-repo.sh makes it).
#
# Big uploads to GitHub time out (HTTP 408) on a slow line, so changes go up
# in batches of about 40 MB, each pushed by itself; the virtual PC's
# manifest.json comes last, so the Try page only sees a complete PC.
set -e
cd "$(dirname "$0")/.."
W=out/gh-pages
REMOTE=$(git remote get-url origin)
[ -d "$W/.git" ] || git clone -q --branch gh-pages "$REMOTE" "$W"
git -C "$W" fetch -q origin gh-pages
git -C "$W" checkout -q gh-pages 2>/dev/null || git -C "$W" checkout -q -b gh-pages origin/gh-pages
git -C "$W" reset -q --hard origin/gh-pages

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

# The changes, in batches.
push() { # push MESSAGE: commit what is staged and push it, trying again on errors
    git -C "$W" diff --cached --quiet && return 0
    git -C "$W" commit -q -m "$1"
    for try in 1 2 3 4 5; do
        git -C "$W" push -q origin gh-pages && return 0
        echo "(push failed, trying again in 20 s)"
        sleep 20
    done
    echo "Pushing failed: run tools/publish-site.sh again later (it carries on)." >&2
    exit 1
}
rev=$(git rev-parse --short HEAD)
# 1: the pages, the emulator and what was removed (not yet the new manifest)
git -C "$W" add -A -- . ':!try/disk'
git -C "$W" add -u -- try/disk ':!try/disk/manifest.json' 2>/dev/null || true
push "Website ($rev)"
# 2: the virtual PC's disk pieces and state, about 40 MB at a time
batch=0 n=0
git -C "$W" ls-files -o --exclude-standard -- try/disk ':!try/disk/manifest.json' | sort > out/publish-new.txt
while IFS= read -r f; do
    git -C "$W" add -- "$f"
    batch=$(( batch + $(stat -f %z "$W/$f" 2>/dev/null || stat -c %s "$W/$f") ))
    n=$(( n + 1 ))
    if [ $batch -ge 40000000 ]; then
        push "Website: the virtual PC, part ($n files)"
        echo "  $n of $(wc -l < out/publish-new.txt) files up"
        batch=0
    fi
done < out/publish-new.txt
git -C "$W" add -u -- try/disk ':!try/disk/manifest.json' 2>/dev/null || true
push "Website: the virtual PC, last part"
# 3: the manifest: now the Try page uses the new PC
git -C "$W" add -A -- try/disk/manifest.json 2>/dev/null || true
push "Website: the virtual PC is ready ($rev)"
echo "Published: https://jgm240.github.io/kilobyte/"
