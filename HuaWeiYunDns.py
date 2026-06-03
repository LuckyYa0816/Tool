# -*- coding: utf-8 -*-
import os
import re
import requests
from bs4 import BeautifulSoup
from collections import defaultdict
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkdns.v2 import *
from huaweicloudsdkdns.v2.region.dns_region import DnsRegion
from huaweicloudsdkcore.exceptions import exceptions

# ── 全局配置 ──────────────────────────────────────────────────
IP_COUNT = 1          # ← 每个运营商线路更新的 IP 数量，改这里即可

# 配置你的多个域名
ROOT_DOMAIN_1 = "cfyx.19990816.xyz."


# ── 解析工具函数 ──────────────────────────────────────────────

def _parse_speed(text):
    m = re.search(r'([\d.]+)\s*mb/s', text, re.IGNORECASE)
    if m: return float(m.group(1))
    m = re.search(r'([\d.]+)\s*Mbps', text, re.IGNORECASE)
    if m: return float(m.group(1))
    m = re.search(r'([\d.]+)\s*M\b', text)
    if m: return float(m.group(1))
    return 0.0

def _parse_latency(text):
    m = re.search(r'([\d.]+)\s*ms', text, re.IGNORECASE)
    return float(m.group(1)) if m else float('inf')


# ── 各运营商 IP 抓取函数 (原有逻辑) ──────────────────────────

def _fetch_mobile_ips():
    url = "https://raw.githubusercontent.com/svip-s/cloudflare_ip/refs/heads/main/best_ips.txt"
    try:
        lines = requests.get(url, timeout=15).text.splitlines()
        candidates = []
        for line in lines:
            line = line.strip()
            if not line: continue
            ip_port_part = line.split('#')[0].strip()
            parts = ip_port_part.split(':')
            if len(parts) != 2: continue
            ip, port = parts[0].strip(), parts[1].strip()
            if port != '443': continue
            candidates.append((ip, _parse_speed(line), _parse_latency(line)))
        candidates.sort(key=lambda x: (-x[1], x[2]))
        result = [c[0] for c in candidates[:IP_COUNT]]
        print(f"📡 移动 原始候选 {len(candidates)} 条，选取 {IP_COUNT} 个: {result}")
        return result
    except Exception as e:
        print(f"❌ 移动 IP 抓取失败: {e}")
        return []

def _fetch_junzhen_ips(url, label):
    try:
        lines = requests.get(url, timeout=15).text.splitlines()
        candidates = []
        for line in lines:
            line = line.strip()
            if not line: continue
            ip_port_part = line.split('#')[0].strip()
            parts = ip_port_part.split(':')
            if len(parts) != 2: continue
            ip, port = parts[0].strip(), parts[1].strip()
            if port != '443': continue
            candidates.append((ip, _parse_speed(line)))
        candidates.sort(key=lambda x: -x[1])
        result = [c[0] for c in candidates[:IP_COUNT]]
        print(f"📡 {label} 原始候选 {len(candidates)} 条，选取 {IP_COUNT} 个: {result}")
        return result
    except Exception as e:
        print(f"❌ {label} IP 抓取失败: {e}")
        return []

def _fetch_fallback_ips(missing_carriers):
    if not missing_carriers:
        return {}
    url = "https://bestcf.pages.dev/uouin/all.txt"
    carrier_map = {"电信": [], "联通": [], "移动": []}
    try:
        lines = requests.get(url, timeout=15).text.splitlines()
        for line in lines:
            line = line.strip()
            if not line: continue
            ip_port_part = line.split('#')[0].strip()
            parts = ip_port_part.split(':')
            if len(parts) != 2: continue
            ip, port = parts[0].strip(), parts[1].strip()
            if port != '443': continue
            fields = line.split('|')
            if len(fields) < 2: continue
            carrier_field = fields[1].strip()
            for carrier in carrier_map:
                if carrier in carrier_field:
                    carrier_map[carrier].append((ip, _parse_speed(line), _parse_latency(line)))
                    break
        result = {}
        for carrier in missing_carriers:
            candidates = carrier_map.get(carrier, [])
            candidates.sort(key=lambda x: (-x[1], x[2]))
            ips = [c[0] for c in candidates[:IP_COUNT]]
            print(f"🛡️ 保底 [{carrier}] 候选 {len(candidates)} 条，选取 {IP_COUNT} 个: {ips}")
            result[carrier] = ips
        return result
    except Exception as e:
        print(f"❌ 保底 IP 抓取失败: {e}")
        return {c: [] for c in missing_carriers}

def get_best_ips_domain1():
    print(f"\n--- 开始获取 {ROOT_DOMAIN_1} 的优选 IP ---")
    best = {
        "移动": _fetch_mobile_ips(),
        "联通": _fetch_junzhen_ips("https://cf.junzhen.qzz.io/best_ips.txt",    "联通"),
        "电信": _fetch_junzhen_ips("https://cf.junzhen.qzz.io/best_ips_bj.txt", "电信"),
    }
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
        lines = {'电信': 'Dianxin', '联通': 'Liantong', '移动': 'Yidong'}
        return lines.get(carrier_name, None)

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

            for carrier, ips in carrier_ips.items():
                if not ips: continue
                line_code = self.get_line_code(carrier)
                if not line_code:
                    print(f"⚠️ [{carrier}] 未知运营商，跳过。")
                    continue
                new_ips_sorted = sorted(ips)
                if line_code in existing_map:
                    rs = existing_map[line_code]
                    old_ips_sorted = sorted(rs.records)
                    if old_ips_sorted == new_ips_sorted:
                        print(f"✅ [{carrier}] 无变动，跳过。")
                    else:
                        print(f"🔄 [{carrier}] 更新: {old_ips_sorted} -> {new_ips_sorted}")
                        update_req = UpdateRecordSetRequest()
                        update_req.zone_id = zone_id
                        update_req.recordset_id = rs.id
                        update_req.body = UpdateRecordSetReq(records=new_ips_sorted)
                        self.client.update_record_set(update_req)
                else:
                    print(f"⚠️ [{carrier}] 华为云缺少 '{line_code}' 线路记录，请先手动创建。")

        except exceptions.ClientRequestException as e:
            print(f"❌ API 异常: {e.error_msg}")


# ── 入口 ─────────────────────────────────────────────────────

if __name__ == '__main__':
    ak     = os.getenv("HW_AK")
    sk     = os.getenv("HW_SK")
    prj_id = os.getenv("HW_PROJECT_ID")
    region = os.getenv("HW_REGION", "ap-southeast-1")

    # 初始化管理器
    manager = HuaWeiDNSManager(ak, sk, region, prj_id)

    # 任务 1：更新原有域名 (使用原来的抓取源)
    ips_domain1 = get_best_ips_domain1()
    if any(ips_domain1.values()):
        manager.sync_dns(ROOT_DOMAIN_1, ips_domain1)
    else:
        print(f"❌ 未获取到 {ROOT_DOMAIN_1} 的有效 IP 数据")
