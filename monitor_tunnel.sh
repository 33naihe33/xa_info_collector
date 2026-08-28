#!/bin/bash
# 隧道监控脚本：每5分钟检查，断开自动重连
SUBDOMAIN="xiongan-biz"
PORT=8000
LOG="/tmp/tunnel_monitor.log"

while true; do
    # 检查后端
    BACKEND=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$PORT/api/collect/sources 2>/dev/null)
    # 检查公网隧道
    TUNNEL=$(curl -s -o /dev/null -w "%{http_code}" https://$SUBDOMAIN.loca.lt/ 2>/dev/null)
    
    echo "$(date '+%Y-%m-%d %H:%M:%S') 后端:$BACKEND 隧道:$TUNNEL" >> $LOG
    
    # 后端挂了，重启
    if [ "$BACKEND" != "200" ]; then
        echo "$(date '+%H:%M:%S') 后端异常，重启中..." >> $LOG
        pkill -f "uvicorn web.app" 2>/dev/null; sleep 2
        cd /Users/utopia/Code/xa_info_collector
        source .venv/bin/activate
        export $(grep ZHIPUAI_API_KEY .env | xargs)
        nohup uvicorn web.app:create_app --factory --host 127.0.0.1 --port 8000 > /dev/null 2>&1 &
        sleep 5
    fi
    
    # 隧道断了，重连
    if [ "$TUNNEL" != "200" ]; then
        echo "$(date '+%H:%M:%S') 隧道异常，重连中..." >> $LOG
        pkill -f "lt --port" 2>/dev/null; sleep 2
        nohup npx lt --port $PORT --subdomain $SUBDOMAIN > /dev/null 2>&1 &
        sleep 5
    fi
    
    sleep 300  # 5分钟检查一次
done
