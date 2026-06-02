# -*- coding: utf-8 -*-
import os
import re
import requests
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkdns.v2 import *
from huaweicloudsdkdns.v2.region.dns_region import DnsRegion
from huaweicloudsdkcore.exceptions import exceptions


# ── 解析工具函数 ──────────────────────────────────────────────

def _parse_speed(text):
    """提取速度值，支持 8.6Mbps / 19M / 67.50mb/s 三种格式，返回 float"""
    m = re.search(r'([\d.]+)\s*mb/s', text, re.IGNORECASE)
    if m:
        return float(m.group(1))
    m = re.search(r'([\d.]+)\s*Mbps', text, re.IGNORECASE)
    if m:
        return float(m.group(1))
    m = re.search(r'([\d.]+)\s*M\b', text)
    if m:
        return float(m.group(1))
    return 0.0

def _parse_latency(text):
    """提取延迟值 ms，返回 float；无则返回无穷大"""
    m = re.search(r'([\d.]+)\s*ms', text, re.IGNORECASE)
    return float(m.group(1)) if m else float('inf')


# ── 各运营商 IP 抓取函数 ──────────────────────────────────────

def _fetch_mobile_ips(count=3):
    """
    移动主力源：best_ips.txt
    格式：152.70.253.84:8443#KR [优选高速 355.36ms 8.6Mbps]
    筛选：仅 443 端口，速度降序 + 延迟升序
    """
    url = "https://raw.githubusercontent.com/svip-s/cloudflare_ip/refs/heads/main/best_ips.txt"
    try:
        lines = requests.get(url, timeout=15).text.splitlines()
        candidates = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            ip_port_part = line.split('#')[0].strip()
            parts = ip_port_part.split(':')
            if len(parts) != 2:
                continue
            ip, port = parts[0].strip(), parts[1].strip()
            if port != '443':
                continue
            candidates.append((ip, _parse_speed(line), _parse_latency(line)))
        candidates.sort(key=lambda x: (-x[1], x[2]))
        result = [c[0] for c in candidates[:count]]
        print(f"📡 移动 原始候选 {len(candidates)} 条，选取: {result}")
        return result
    except Exception as e:
        print(f"❌ 移动 IP 抓取失败: {e}")
        return []


def _fetch_junzhen_ips(url, label, count=3):
    """
    联通/电信主力源：junzhen 接口
    格式：172.67.75.97:443#CA [高速 by Jz 19M]
    筛选：仅 443 端口，速度降序
    """
    try:
        lines = requests.get(url, timeout=15).text.splitlines()
        candidates = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            ip_port_part = line.split('#')[0].strip()
            parts = ip_port_part.split(':')
            if len(parts) != 2:
                continue
            ip, port = parts[0].strip(), parts[1].strip()
            if port != '443':
                continue
            candidates.append((ip, _parse_speed(line)))
        candidates.sort(key=lambda x: -x[1])
        result = [c[0] for c in candidates[:count]]
        print(f"📡 {label} 原始候选 {len(candidates)} 条，选取: {result}")
        return result
    except Exception as e:
        print(f"❌ {label} IP 抓取失败: {e}")
        return []


def _fetch_fallback_ips(missing_carriers, count=3):
    """
    保底策略：从 bestcf all.txt 为缺失的运营商补充 IP
    格式：162.159.41.4:443#麒麟优选 | 电信 | 162.159.41.4 | 46.42ms | 67.50mb/s
    筛选：仅 443 端口，速度降序 + 延迟升序
    运营商关键字映射：电信 / 联通 / 移动
    """
    if not missing_carriers:
        return {}

    url = "https://bestcf.pages.dev/uouin/all.txt"
    carrier_map = {"电信": [], "联通": [], "移动": []}

    try:
        lines = requests.get(url, timeout=15).text.splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # 取 ip:port 部分（# 前）
            ip_port_part = line.split('#')[0].strip()
            parts = ip_port_part.split(':')
            if len(parts) != 2:
                continue
            ip, port = parts[0].strip(), parts[1].strip()
            if port != '443':
                continue

            # 从竖线分隔的字段里找运营商标签
            # 格式：xxx#标签 | 运营商 | ip | 延迟 | 速度
            fields = line.split('|')
            if len(fields) < 2:
                continue
            carrier_field = fields[1].strip()  # 第2段即运营商

            for carrier in carrier_map:
                if carrier in carrier_field:
                    speed   = _parse_speed(line)
                    latency = _parse_latency(line)
                    carrier_map[carrier].append((ip, speed, latency))
                    break  # 一行只归属一个运营商

        result = {}
        for carrier in missing_carriers:
            candidates = carrier_map.get(carrier, [])
            candidates.sort(key=lambda x: (-x[1], x[2]))
            ips = [c[0] for c in candidates[:count]]
            print(f"🛡️ 保底 [{carrier}] 候选 {len(candidates)} 条，选取: {ips}")
            result[carrier] = ips

        return result

    except Exception as e:
        print(f"❌ 保底 IP 抓取失败: {e}")
        return {c: [] for c in missing_carriers}


def get_best_ips():
    """获取三网最优各 3 个 IP；任一运营商无结果时启用保底接口"""
    best = {
        "移动": _fetch_mobile_ips(),
        "联通": _fetch_junzhen_ips("https://cf.junzhen.qzz.io/best_ips.txt",    "联通"),
        "电信": _fetch_junzhen_ips("https://cf.junzhen.qzz.io/best_ips_bj.txt", "电信"),
    }

    # 找出没拿到 IP 的运营商
    missing = [carrier for carrier, ips in best.items() if not ips]

    if missing:
        print(f"⚠️ 以下运营商主力源无结果，启用保底接口: {missing}")
        fallback = _fetch_fallback_ips(missing)
        for carrier, ips in fallback.items():
            if ips:
                best[carrier] = ips
                print(f"✅ 保底补充 [{carrier}]: {ips}")
            else:
                print(f"❌ 保底接口也未获取到 [{carrier}] 的 IP")

    return best


# ── 华为云 DNS 管理器 ─────────────────────────────────────────

class HuaWeiDNSManager:
    def __init__(self, ak, sk, region_id, project_id=None):
        credentials = BasicCredentials(ak, sk)
        if project_id:
            credentials.with_project_id(project_id)
        self.client = DnsClient.new_builder() \
            .with_credentials(credentials) \
            .with_region(DnsRegion.value_of(region_id)) \
            .build()

    def get_line_code(self, carrier_name):
        lines = {
            '电信': 'Dianxin',
            '联通': 'Liantong',
            '移动': 'Yidong',
            '默认': 'default_view'
        }
        return lines.get(carrier_name, 'default_view')

    def get_zone_id(self, domain):
        try:
            request = ListPublicZonesRequest()
            response = self.client.list_public_zones(request)
            search_name = domain if domain.endswith('.') else f"{domain}."
            for zone in response.zones:
                if zone.name == search_name:
                    return zone.id
            return None
        except Exception as e:
            print(f"❌ 获取 Zone ID 失败: {e}")
            return None

    def sync_dns(self, root_domain, carrier_ips):
        zone_id = self.get_zone_id(root_domain)
        if not zone_id:
            print(f"❌ 错误: 未找到域名 {root_domain} 的解析区")
            return

        full_name = root_domain if root_domain.endswith('.') else f"{root_domain}."

        try:
            req = ListRecordSetsWithLineRequest()
            req.zone_id = zone_id
            req.name = full_name
            req.type = "A"
            resp = self.client.list_record_sets_with_line(req)
            existing_map = {rs.line: rs for rs in resp.recordsets}

            sync_tasks = []
            for carrier, ips in carrier_ips.items():
                if not ips:
                    continue
                line_code = self.get_line_code(carrier)
                sync_tasks.append((carrier, line_code, ips))
                if carrier == "电信":
                    sync_tasks.append(("默认(跟随电信)", "default_view", ips))

            for task_name, line_code, new_ips in sync_tasks:
                new_ips_sorted = sorted(new_ips)
                if line_code in existing_map:
                    rs = existing_map[line_code]
                    old_ips_sorted = sorted(rs.records)
                    if old_ips_sorted == new_ips_sorted:
                        print(f"✅ [{task_name}] 无变动，跳过。")
                    else:
                        print(f"🔄 [{task_name}] 更新: {old_ips_sorted} -> {new_ips_sorted}")
                        update_req = UpdateRecordSetRequest()
                        update_req.zone_id = zone_id
                        update_req.recordset_id = rs.id
                        update_req.body = UpdateRecordSetReq(records=new_ips_sorted)
                        self.client.update_record_set(update_req)
                else:
                    print(f"⚠️ [{task_name}] 华为云缺少 '{line_code}' 线路记录，请先手动创建。")

        except exceptions.ClientRequestException as e:
            print(f"❌ API 异常: {e.error_msg}")


# ── 入口 ─────────────────────────────────────────────────────

if __name__ == '__main__':
    ak     = os.getenv("HW_AK")
    sk     = os.getenv("HW_SK")
    prj_id = os.getenv("HW_PROJECT_ID")
    region = os.getenv("HW_REGION", "ap-southeast-1")

    ROOT_DOMAIN = "cfyx.19990816.xyz."

    best_ips = get_best_ips()

    if any(best_ips.values()):
        manager = HuaWeiDNSManager(ak, sk, region, prj_id)
        manager.sync_dns(ROOT_DOMAIN, best_ips)
    else:
        print("❌ 未获取到有效 IP 数据")
