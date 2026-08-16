#!/bin/bash
# ============================================================
# GitLab 分支批量合并 - Web 管理台启动脚本
# 用法：在「终端」App 中执行  ./start_webapp.sh
#       自定义端口：./start_webapp.sh 9000
# 首次运行若系统询问访问「文稿」文件夹，请点击「允许」。
# ============================================================
cd "$(dirname "$0")"

PORT="${1:-8765}"

# 若端口被占用则先提示
if lsof -ti :"$PORT" >/dev/null 2>&1; then
    echo "[提示] 端口 $PORT 已被占用，服务可能已在运行，先停止旧进程..."
    lsof -ti :"$PORT" | xargs kill 2>/dev/null
    sleep 1
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

exec python3 webapp.py --port "$PORT"
