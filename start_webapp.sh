#!/bin/bash
# ============================================================
# GitLab 分支批量合并 - Web 管理台启动脚本
# 用法：在「终端」App 中执行  ./start_webapp.sh
#       自定义端口：./start_webapp.sh 9000
# 首次运行若系统询问访问「文稿」文件夹，请点击「允许」。
# ============================================================
cd "$(dirname "$0")"

PORT="${1:-8765}"

if [ -f "frontend/package.json" ]; then
    echo "[构建] 正在构建前端产物..."
    (
        cd frontend
        INSTALLED_VITE="$(node -e 'try { console.log(require("./node_modules/vite/package.json").version) } catch (e) {}' 2>/dev/null)"
        case "$INSTALLED_VITE" in
            4.*|"")
                ;;
            *)
                echo "[错误] 当前 node_modules 中的 vite 版本是 ${INSTALLED_VITE}，但项目需要 package-lock.json 中的 Vite 4。"
                echo "       请执行："
                echo "         cd frontend"
                echo "         npm ci"
                echo "         cd .."
                echo "         ./start_webapp.sh"
                exit 2
                ;;
        esac
        npm run build
    )
    BUILD_STATUS=$?
    if [ $BUILD_STATUS -eq 2 ]; then
        exit 1
    fi
    if [ $BUILD_STATUS -ne 0 ]; then
        echo "[错误] 前端构建失败，已停止启动，避免继续使用旧页面。"
        echo "       请先在 frontend 目录执行 npm ci 或 npm install 修复依赖后重试。"
        exit 1
    fi
fi

# 若端口被占用则先提示
if lsof -ti :"$PORT" >/dev/null 2>&1; then
    echo "[提示] 端口 $PORT 已被占用，服务可能已在运行，先停止旧进程..."
    for pid in $(lsof -ti :"$PORT"); do
        kill "$pid" 2>/dev/null
    done
    for i in 1 2 3 4 5; do
        if ! lsof -ti :"$PORT" >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    if lsof -ti :"$PORT" >/dev/null 2>&1; then
        echo "[提示] 旧进程未正常退出，强制停止..."
        for pid in $(lsof -ti :"$PORT"); do
            kill -9 "$pid" 2>/dev/null
        done
        sleep 1
    fi
    if lsof -ti :"$PORT" >/dev/null 2>&1; then
        echo "[错误] 端口 $PORT 仍被占用，请手动关闭占用进程后重试。"
        exit 1
    fi
fi

echo "============================================"
echo "  GitLab 分支合并管理台"
echo "  访问地址: http://127.0.0.1:$PORT/"
echo "  项目目录: $(pwd)"
if [ -f "dist/index.html" ]; then
    echo "  前端产物: dist/index.html"
else
    echo "  前端产物: 未找到 dist/index.html，将回退到根目录 index.html"
fi
echo "  按 Ctrl+C 停止服务"
echo "============================================"

python3 webapp.py --port "$PORT" &
APP_PID=$!

cleanup() {
    kill "$APP_PID" 2>/dev/null
}
trap cleanup INT TERM EXIT

for i in 1 2 3 4 5 6 7 8 9 10; do
    if python3 - "$PORT" <<'PY' >/dev/null 2>&1
import sys
from urllib.request import urlopen
port = sys.argv[1]
with urlopen(f"http://127.0.0.1:{port}/api/state", timeout=1) as resp:
    raise SystemExit(0 if resp.status == 200 else 1)
PY
    then
        echo "[就绪] 后端接口已响应: http://127.0.0.1:$PORT/api/state"
        wait "$APP_PID"
        exit $?
    fi
    if ! kill -0 "$APP_PID" 2>/dev/null; then
        echo "[错误] 后端进程启动后已退出。"
        wait "$APP_PID"
        exit $?
    fi
    sleep 1
done

echo "[错误] 后端已启动但接口未响应，请检查终端中的 Python 报错。"
exit 1
