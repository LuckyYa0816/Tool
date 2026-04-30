# -*- coding: utf-8 -*-
import os
import requests
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkdns.v2 import *
from huaweicloudsdkdns.v2.region.dns_region import DnsRegion
from huaweicloudsdkcore.exceptions import exceptions

class HuaWeiDNSManager:
    def __init__(self, ak, sk, region_id, project_id=None):
        # 显式传入 Project ID 解决权限探测导致的 400 错误
        credentials = BasicCredentials(ak, sk)
        if project_id:
            credentials.with_project_id(project_id)
            
        self.client = DnsClient.new_builder() \
            .with_credentials(credentials) \
            .with_region(DnsRegion.value_of(region_id)) \
            .build()

    def get_line_code(self, carrier_name):
        """映射中文运营商到华为云线路代码"""
        lines = {
            '电信': 'Dianxin',
            '联通': 'Liantong',
            '移动': 'Yidong',
            '默认': 'default_view'
        }
        return lines.get(carrier_name, 'default_view')

    def get_zone_id(self, domain):
        """自动根据域名获取 Zone ID"""
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

    def sync_dns(self, root_domain, sub_domain, carrier_ips):
        """同步多线路 IP"""
        zone_id = self.get_zone_id(root_domain)
        if not zone_id:
            print(f"❌ 错误: 未找到域名 {root_domain} 的解析区")
            return

        full_name = f"{sub_domain}.{root_domain}" if root_domain.endswith('.') else f"{sub_domain}.{root_domain}."

        try:
            req = ListRecordSetsWithLineRequest()
            req.zone_id = zone_id
            req.name = full_name
            req.type = "A"
            resp = self.client.list_record_sets_with_line(req)
            
            existing_map = {rs.line: rs for rs in resp.recordsets}

            for carrier, new_ips in carrier_ips.items():
                if not new_ips: continue
                line_code = self.get_line_code(carrier)
                new_ips_sorted = sorted(new_ips)

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

def get_best_ips():
    """获取三网最优各 3 个 IP"""
    url = "https://bestcf.pages.dev/vvhan/ipv4.txt"
    try:
        res = requests.get(url, timeout=15).text.splitlines()
        ips = {"电信": [], "联通": [], "移动": []}
        for line in res:
            if not line.strip(): continue
            ip = line.split()[0].split('#')[0].split(',')[0].strip()
            for key in ips.keys():
                if key in line and len(ips[key]) < 3:
                    ips[key].append(ip)
        return ips
    except Exception as e:
        print(f"❌ IP 抓取失败: {e}")
        return {}

if __name__ == '__main__':
    # 读取你要求的 Secrets 命名
    ak = os.getenv("HW_AK")
    sk = os.getenv("HW_SK")
    prj_id = os.getenv("HW_PROJECT_ID")
    region = os.getenv("HW_REGION", "ap-southeast-1")
    
    # 你的域名信息
    ROOT_DOMAIN = "19990816.xyz."
    SUB_DOMAIN = "cfyx"

    best_ips = get_best_ips()
    
    if any(best_ips.values()):
        manager = HuaWeiDNSManager(ak, sk, region, prj_id)
        manager.sync_dns(ROOT_DOMAIN, SUB_DOMAIN, best_ips)
    else:
        print("❌ 未获取到有效 IP 数据")
