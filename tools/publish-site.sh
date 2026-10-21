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
