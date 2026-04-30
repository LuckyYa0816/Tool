# -*- coding: utf-8 -*-
import os
import requests
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkdns.v2 import *
from huaweicloudsdkdns.v2.region.dns_region import DnsRegion
from huaweicloudsdkcore.exceptions import exceptions

class HuaWeiDNSManager:
    def __init__(self, ak, sk, region_id, project_id=None):
        self.ak = ak
        self.sk = sk
        self.region = region_id
        
        # 1. 初始化凭证，显式传入 project_id 解决之前的 400 认证错误
        credentials = BasicCredentials(self.ak, self.sk)
        if project_id:
            credentials.with_project_id(project_id)
            
        self.client = DnsClient.new_builder() \
            .with_credentials(credentials) \
            .with_region(DnsRegion.value_of(self.region)) \
            .build()

    def get_line_code(self, carrier_name):
        """将中文运营商名称转换为华为云线路代码"""
        lines = {
            '电信': 'Dianxin',
            '联通': 'Liantong',
            '移动': 'Yidong',
            '默认': 'default_view'
        }
        return lines.get(carrier_name, 'default_view')

    def get_zone_id(self, domain):
        """根据域名自动获取 Zone ID"""
        try:
            request = ListPublicZonesRequest()
            response = self.client.list_public_zones(request)
            # 华为云 API 匹配通常需要末尾带点，如 19990816.xyz.
            search_name = domain if domain.endswith('.') else f"{domain}."
            for zone in response.zones:
                if zone.name == search_name:
                    return zone.id
            return None
        except Exception as e:
            print(f"❌ 获取 Zone ID 失败: {e}")
            return None

    def sync_dns(self, root_domain, sub_domain, carrier_ips):
        """同步三网 IP 到华为云"""
        zone_id = self.get_zone_id(root_domain)
        if not zone_id:
            print(f"❌ 错误: 在该账号下未找到域名 {root_domain} 的解析区")
            return

        # 构造完整记录名，如 proxy.19990816.xyz.
        full_name = f"{sub_domain}.{root_domain}" if root_domain.endswith('.') else f"{sub_domain}.{root_domain}."

        try:
            # 获取该子域名现有的所有线路记录
            req = ListRecordSetsWithLineRequest()
            req.zone_id = zone_id
            req.name = full_name
            req.type = "A"
            resp = self.client.list_record_sets_with_line(req)
            
            # 建立现有记录映射 { 'Dianxin': rs_object }
            existing_map = {rs.line: rs for rs in resp.recordsets}

            for carrier, new_ips in carrier_ips.items():
                if not new_ips: continue
                line_code = self.get_line_code(carrier)
                new_ips_sorted = sorted(new_ips)

                if line_code in existing_map:
                    rs = existing_map[line_code]
                    old_ips_sorted = sorted(rs.records)

                    if old_ips_sorted == new_ips_sorted:
                        print(f"✅ [{carrier}] 记录已是最新 ({new_ips_sorted})，跳过更新。")
                    else:
                        print(f"🔄 [{carrier}] 检测到变动: {old_ips_sorted} -> {new_ips_sorted}")
                        update_req = UpdateRecordSetRequest()
                        update_req.zone_id = zone_id
                        update_req.recordset_id = rs.id
                        # 更新该线路下的 3 个 IP
                        update_req.body = UpdateRecordSetReq(records=new_ips_sorted)
                        self.client.update_record_set(update_req)
                else:
                    print(f"⚠️ [{carrier}] 华为云中未找到对应线路记录，请先手动创建 '{line_code}' 线路的 A 记录。")

        except exceptions.ClientRequestException as e:
            print(f"❌ API 调用异常: {e.error_msg}")

def get_best_ips():
    """获取接口数据并筛选三网最优各 3 个 IP"""
    url = "https://bestcf.pages.dev/vvhan/ipv4.txt"
    try:
        print(f"🌐 正在从接口获取最新 IP...")
        res = requests.get(url, timeout=15).text.splitlines()
    except Exception as e:
        print(f"❌ 抓取 IP 接口失败: {e}")
        return {}

    ips = {"电信": [], "联通": [], "移动": []}
    for line in res:
        if not line.strip(): continue
        # 提取 IP (处理包含 # 或 , 的情况)
        ip = line.split()[0].split('#')[0].split(',')[0].strip()
        
        for key in ips.keys():
            if key in line and len(ips[key]) < 3:
                ips[key].append(ip)
    return ips

if __name__ == '__main__':
    # --- 配置区 (通过 GitHub Secrets 注入) ---
    AK = os.getenv("CLOUD_SDK_AK")
    SK = os.getenv("CLOUD_SDK_SK")
    PRJ_ID = os.getenv("HW_PROJECT_ID") # 解决 400 错误的关键
    REGION = os.getenv("HW_REGION", "ap-southeast-1")
    
    # 目标域名配置
    MY_ROOT_DOMAIN = "19990816.xyz." # 记得带点
    MY_SUB_DOMAIN = "cfyx"          # 你的子域名
    # ---------------------------------------

    # 1. 获取最优 IP
    target_ips = get_best_ips()
    
    if not any(target_ips.values()):
        print("❌ 未能获取到任何有效 IP，程序退出。")
    else:
        # 2. 执行同步
        manager = HuaWeiDNSManager(AK, SK, REGION, PRJ_ID)
        manager.sync_dns(MY_ROOT_DOMAIN, MY_SUB_DOMAIN, target_ips)
