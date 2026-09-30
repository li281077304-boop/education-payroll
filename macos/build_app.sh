#!/bin/sh
# Build the PRODUCTION LOCAL APP bundles for the Payroll tool.
#
#   macos/build_app.sh [--install] [--desktop] [output_dir]
#
#   --install   also copy the bundles into ~/Applications
#   --desktop   also place Desktop shortcuts (symlinks) next to the copy
#
# The bundles stay small (no Electron/Tauri), but include a repo-independent
# shell bootstrap so a stale checkout can never silently exit before showing a
# useful diagnostic.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
BUILD_SHA=$(git -C "$REPO_ROOT" rev-parse --verify HEAD 2>/dev/null || true)
if [ -z "$BUILD_SHA" ]; then
    echo "无法确定构建提交号，拒绝生成无法追溯版本的工资助手。" >&2
    exit 1
fi
BUILD_DIRTY=0
if [ -n "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)" ]; then
    echo "只能从干净的已提交工作区构建 Mac 工资核算助手。" >&2
    exit 1
fi
RELEASE_VERSION="Payroll-V1"

INSTALL=0
DESKTOP=0
OUTPUT_DIR=""
for arg in "$@"; do
    case "$arg" in
        --install) INSTALL=1 ;;
        --desktop) DESKTOP=1 ;;
        -*) echo "未知参数：$arg" >&2; exit 2 ;;
        *) OUTPUT_DIR="$arg" ;;
    esac
done

if [ -z "$OUTPUT_DIR" ]; then
    OUTPUT_DIR="$REPO_ROOT/macos/dist"
fi

PYTHON="$REPO_ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON=$(command -v python3 || true)
fi
if [ -z "$PYTHON" ] || [ ! -x "$PYTHON" ]; then
    echo "找不到可用的 Python 解释器。" >&2
    exit 1
fi

if [ ! -f "$REPO_ROOT/payroll_ui/server.py" ]; then
    echo "找不到 payroll_ui，检查目录：$REPO_ROOT" >&2
    exit 1
fi

# A single quote in a path would break the generated shim; refuse instead of
# producing a silently broken bundle.
case "$REPO_ROOT$PYTHON" in
    *"'"*) echo "路径中包含单引号，无法生成启动器。" >&2; exit 1 ;;
esac

mkdir -p "$OUTPUT_DIR"

build_bundle() {
    bundle_name="$1"
    mode="$2"
    bundle_id="$3"
    bundle="$OUTPUT_DIR/$bundle_name.app"

    rm -rf "$bundle"
    mkdir -p "$bundle/Contents/MacOS" "$bundle/Contents/Resources"

    cat > "$bundle/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>$bundle_name</string>
    <key>CFBundleDisplayName</key>
    <string>$bundle_name</string>
    <key>CFBundleIdentifier</key>
    <string>$bundle_id</string>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleSignature</key>
    <string>????</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

    printf 'APPL????' > "$bundle/Contents/PkgInfo"

    cp "$SCRIPT_DIR/bootstrap.sh" "$bundle/Contents/Resources/bootstrap.sh"
    chmod +x "$bundle/Contents/Resources/bootstrap.sh"

    cat > "$bundle/Contents/MacOS/launcher" <<SHIM
#!/bin/sh
# This tiny shim resolves bootstrap relative to the app bundle; it does not
# depend on the checkout, Python, Terminal, or Finder's current directory.
CONTENTS_DIR=\$(CDPATH= cd -- "\$(dirname -- "\$0")/.." && pwd)
BOOTSTRAP="\$CONTENTS_DIR/Resources/bootstrap.sh"
if [ ! -x "\$BOOTSTRAP" ]; then
    STATE_DIR="\$HOME/Library/Application Support/EducationPayroll/launcher"
    /bin/mkdir -p "\$STATE_DIR" 2>/dev/null || true
    /usr/bin/printf '[%s] bootstrap BOOTSTRAP_MISSING: app bundle startup component missing\\n' "\$(/bin/date '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null || echo unknown-time)" >> "\$STATE_DIR/diagnostics.log" 2>/dev/null || true
    /usr/bin/printf '# 工资核算助手启动诊断\\n\\n应用内启动组件缺失，请重新安装工资核算助手。\\n' > "\$STATE_DIR/last-problem.md" 2>/dev/null || true
    /usr/bin/osascript -e 'display dialog "工资核算助手启动组件缺失，请重新安装应用。" with title "工资核算助手" buttons {"好"} with icon caution' >/dev/null 2>&1 || true
    exit 1
fi
exec /bin/sh "\$BOOTSTRAP" --mode $mode "\$@"
SHIM
    chmod +x "$bundle/Contents/MacOS/launcher"

    "$PYTHON" - "$bundle/Contents/Resources/launcher.json" "$mode" "$RELEASE_VERSION" "$BUILD_SHA" "$REPO_ROOT" "$PYTHON" "$HOME/Library/Application Support/EducationPayroll" <<'PY'
import json
import sys

target, mode, version, sha, repo_root, python_path, data_dir = sys.argv[1:]
with open(target, "w", encoding="utf-8") as handle:
    json.dump({
        "contract": "payroll-launcher/1", "mode": mode,
        "release_version": version, "build_sha": sha,
        "build_dirty": False, "repo_root": repo_root,
        "python": python_path, "port": 8760, "data_dir": data_dir,
    }, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
PY

    # An unsigned local bundle is fine; clear any inherited quarantine flag.
    xattr -dr com.apple.quarantine "$bundle" 2>/dev/null || true
    echo "已生成：$bundle"
}

build_bundle "工资核算助手" "open" "com.renjie.education-payroll.launcher"
build_bundle "重启工资服务" "restart" "com.renjie.education-payroll.launcher-restart"

if [ "$INSTALL" = "1" ]; then
    TARGET="$HOME/Applications"
    mkdir -p "$TARGET"
    for name in "工资核算助手" "重启工资服务"; do
        rm -rf "$TARGET/$name.app"
        cp -R "$OUTPUT_DIR/$name.app" "$TARGET/$name.app"
        xattr -dr com.apple.quarantine "$TARGET/$name.app" 2>/dev/null || true
        echo "已安装：$TARGET/$name.app"
    done
    if [ "$DESKTOP" = "1" ]; then
        for name in "工资核算助手" "重启工资服务"; do
            ln -sfn "$TARGET/$name.app" "$HOME/Desktop/$name.app"
            echo "已放置桌面入口：$HOME/Desktop/$name.app"
        done
    fi
fi

echo
echo "本机路径："
echo "  正式入口     : $OUTPUT_DIR/工资核算助手.app"
echo "  安全重启入口 : $OUTPUT_DIR/重启工资服务.app"
[ "$INSTALL" = "1" ] && echo "  已安装到     : $HOME/Applications/"
echo "  固定端口     : 8760"
echo "  正式数据目录 : $HOME/Library/Application Support/EducationPayroll"
