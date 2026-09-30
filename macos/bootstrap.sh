#!/bin/sh
# Repo-independent entry point installed inside each Payroll .app bundle.
# This file intentionally uses only macOS tools until repo/Python are validated.
set -u

MODE="${1:-open}"
if [ "$MODE" = "--mode" ]; then
    MODE="${2:-open}"
    shift 2
else
    shift "$#" || true
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd 2>/dev/null || true)
CONFIG="$SCRIPT_DIR/launcher.json"
EXPECTED_DATA_DIR="$HOME/Library/Application Support/EducationPayroll"
DATA_DIR="$EXPECTED_DATA_DIR"
STATE_DIR="$DATA_DIR/launcher"
DIAGNOSTICS="$STATE_DIR/diagnostics.log"
LAST_PROBLEM="$STATE_DIR/last-problem.md"

timestamp() {
    /bin/date '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null || echo unknown-time
}

append_diagnostic() {
    code="$1"
    message="$2"
    /bin/mkdir -p "$STATE_DIR" 2>/dev/null || return 1
    /usr/bin/printf '[%s] bootstrap %s: %s\n' "$(timestamp)" "$code" "$message" >> "$DIAGNOSTICS" 2>/dev/null || return 1
    {
        /usr/bin/printf '# 工资核算助手启动诊断\n\n'
        /usr/bin/printf -- '- 时间：%s\n- 错误代码：%s\n- 说明：%s\n' "$(timestamp)" "$code" "$message"
        /usr/bin/printf -- '- 正式数据目录：%s\n- 启动器配置：%s\n\n' "$DATA_DIR" "$CONFIG"
        /usr/bin/printf '程序已在运行前停止；未切换或新建工资数据库。\n'
    } > "$LAST_PROBLEM" 2>/dev/null || return 1
    return 0
}

show_failure() {
    code="$1"
    message="$2"
    if append_diagnostic "$code" "$message"; then
        diagnostics_hint="诊断已保存到：$LAST_PROBLEM"
    else
        diagnostics_hint="无法写入诊断文件，请检查用户目录的写入权限。"
    fi
    escaped=$(printf '%s' "$message" | /usr/bin/sed 's/\\/\\\\/g; s/"/\\"/g')
    script="display dialog \"工资核算助手无法启动。\\n\\n$escaped\\n\\n$diagnostics_hint\" buttons {\"查看诊断\", \"重试\", \"好\"} default button \"重试\" with title \"工资核算助手\" with icon caution"
    dialog_output=$(/usr/bin/osascript -e "$script" 2>/dev/null || true)
    choice=$(printf '%s' "$dialog_output" | /usr/bin/sed 's/^.*://')
    case "$choice" in
        重试)
            exec /bin/sh "$0" --mode "$MODE"
            ;;
        查看诊断)
            /usr/bin/open "$LAST_PROBLEM" >/dev/null 2>&1 || true
            script="display dialog \"诊断文件已打开。如需重试启动，请点击“重试”。\" buttons {\"重试\", \"好\"} default button \"重试\" with title \"工资核算助手\""
            dialog_output=$(/usr/bin/osascript -e "$script" 2>/dev/null || true)
            choice=$(printf '%s' "$dialog_output" | /usr/bin/sed 's/^.*://')
            [ "$choice" = "重试" ] && exec /bin/sh "$0" --mode "$MODE"
            ;;
    esac
    exit 1
}

json_value() {
    key="$1"
    /usr/bin/plutil -extract "$key" raw -o - "$CONFIG" 2>/dev/null
}

if [ -z "$SCRIPT_DIR" ] || [ ! -f "$CONFIG" ]; then
    show_failure "CONFIG_MISSING" "应用内启动配置不存在或无法读取。请重新安装工资核算助手。"
fi
if ! /usr/bin/plutil -convert xml1 -o /dev/null "$CONFIG" >/dev/null 2>&1; then
    show_failure "CONFIG_INVALID" "应用内启动配置格式错误。请重新安装工资核算助手。"
fi

REPO_ROOT=$(json_value repo_root) || show_failure "CONFIG_INVALID" "启动配置中缺少程序目录。请重新安装工资核算助手。"
PYTHON=$(json_value python) || show_failure "CONFIG_INVALID" "启动配置中缺少 Python 解释器路径。请重新安装工资核算助手。"
CONFIG_DATA_DIR=$(json_value data_dir) || show_failure "CONFIG_INVALID" "启动配置中缺少正式数据目录。请重新安装工资核算助手。"
PORT=$(json_value port) || show_failure "CONFIG_INVALID" "启动配置中缺少服务端口。请重新安装工资核算助手。"
BUILD_SHA=$(/usr/bin/plutil -extract build_sha raw -o - "$CONFIG" 2>/dev/null || true)
RELEASE_VERSION=$(/usr/bin/plutil -extract release_version raw -o - "$CONFIG" 2>/dev/null || echo "Payroll-V1")
BUILD_DIRTY=$(/usr/bin/plutil -extract build_dirty raw -o - "$CONFIG" 2>/dev/null || echo "true")

if [ "$CONFIG_DATA_DIR" != "$EXPECTED_DATA_DIR" ] || [ "$PORT" != "8760" ]; then
    show_failure "PRODUCTION_CONFIG_UNSAFE" "启动配置与固定正式数据目录或端口不一致。为保护工资数据，程序没有启动。"
fi

if [ ! -d "$REPO_ROOT" ] || [ ! -f "$REPO_ROOT/payroll_ui/server.py" ] || [ ! -f "$REPO_ROOT/tools/payroll_launcher/__main__.py" ]; then
    show_failure "REPO_PATH_INVALID" "工资程序目录已移动、改名或不完整。请从已安装的正式程序目录恢复程序文件后重试。"
fi

if [ ! -f "$PYTHON" ] || [ ! -x "$PYTHON" ]; then
    show_failure "PYTHON_PATH_INVALID" "Python 运行环境不存在或不可执行。请修复工资助手运行环境后重试。"
fi

PYTHONPATH="$REPO_ROOT/tools:$REPO_ROOT" "$PYTHON" -c 'import payroll_launcher.cli, payroll_ui.server, payroll_core' >/dev/null 2>&1
IMPORT_STATUS=$?
if [ "$IMPORT_STATUS" -ne 0 ]; then
    # Keep raw interpreter details out of Finder dialogs and the human-facing
    # report. The diagnostic category is actionable without exposing a Python
    # traceback or implementation paths to an ordinary user.
    show_failure "MODULE_IMPORT_FAILED" "工资程序组件无法载入。请查看诊断信息，或重试启动。"
fi

export PAYROLL_LAUNCHER_REPO_ROOT="$REPO_ROOT"
export PAYROLL_LAUNCHER_PYTHON="$PYTHON"
export PAYROLL_LAUNCHER_CONFIG="$CONFIG"
export PAYROLL_BUILD_SHA="$BUILD_SHA"
export PAYROLL_RELEASE_VERSION="$RELEASE_VERSION"
export PAYROLL_BUILD_DIRTY="$BUILD_DIRTY"
export PYTHONPATH="$REPO_ROOT/tools:$REPO_ROOT"
cd "$REPO_ROOT" || show_failure "REPO_CWD_FAILED" "无法进入工资程序目录。"

PREVIOUS_LOG_SIZE=$(/usr/bin/wc -c < "$DIAGNOSTICS" 2>/dev/null || echo 0)
"$PYTHON" -m payroll_launcher --mode "$MODE" "$@"
EXIT_STATUS=$?
CURRENT_LOG_SIZE=$(/usr/bin/wc -c < "$DIAGNOSTICS" 2>/dev/null || echo 0)
if [ "$EXIT_STATUS" -ne 0 ] && [ "$CURRENT_LOG_SIZE" -le "$PREVIOUS_LOG_SIZE" ]; then
    show_failure "LAUNCHER_PROCESS_FAILED" "工资启动程序意外退出，且没有生成诊断记录。请查看诊断并重试。"
fi
exit "$EXIT_STATUS"
